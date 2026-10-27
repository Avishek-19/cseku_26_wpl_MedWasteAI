"""Development GPS simulator.

The simulator is deliberately backend-side: it feeds generated locations through
the same TrackingService -> database -> WebSocket path as a real GPS source.
It is intended for local development/testing only.
"""
from __future__ import annotations

import asyncio
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models.route import Route, RouteStatus, RouteStopStatus, RouteDestinationState
from app.models.pickup_request import PickupRequest
from app.models.roles import UserRole
from app.models.tracking import LocationSource, TrackingSession, TrackingSessionStatus
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.waste_enums import VehicleStatus
from app.repositories.route_repository import RouteRepository
from app.realtime.tracking_manager import route_topic, tracking_manager, vehicle_topic
from app.repositories.tracking_repository import TrackingRepository
from app.repositories.user_repository import UserRepository
from app.services.tracking_service import TrackingForbiddenError, TrackingService
from app.schemas.tracking import GPSLocationCreate


class SimulatorError(Exception):
    pass


@dataclass
class SimulationState:
    simulation_id: uuid.UUID
    vehicle_id: uuid.UUID
    route_id: uuid.UUID
    tracking_session_id: uuid.UUID
    speed_multiplier: float
    status: str
    progress: float
    task: asyncio.Task[Any] | None = None


def _route_coordinates(route: Route, db: Session) -> list[tuple[float, float]]:
    """Return [lon, lat] coordinates from persisted route geometry.

    OSRM GeoJSON is preferred. If a route was created with the offline
    haversine provider and has no geometry, persisted origin/stops/destination
    are used as waypoints so the simulator still exercises the real route.
    """
    geometry = route.geometry or {}
    coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
    if isinstance(coords, list) and len(coords) >= 2:
        result = []
        for pair in coords:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                result.append((float(pair[0]), float(pair[1])))
        if len(result) >= 2:
            return result

    points: list[tuple[float, float]] = []
    if route.origin_longitude is not None and route.origin_latitude is not None:
        points.append((float(route.origin_longitude), float(route.origin_latitude)))
    # Route has no ORM relationship to stops in the existing model; callers
    # inject persisted stop waypoints when geometry is unavailable.
    stops = RouteRepository(db).list_stops(route.id)
    for stop in stops:
        # The route can change after this simulation starts. Never plot a
        # cancelled or already-served hospital stop as an upcoming waypoint.
        if route.status == RouteStatus.ACTIVE and stop.status not in {
            RouteStopStatus.PENDING, RouteStopStatus.EN_ROUTE, RouteStopStatus.ARRIVED
        }:
            continue
        points.append((float(stop.longitude), float(stop.latitude)))
    if route.destination_longitude is not None and route.destination_latitude is not None:
        points.append((float(route.destination_longitude), float(route.destination_latitude)))
    if len(points) < 2:
        raise SimulatorError("Route has no usable geometry or waypoints.")
    return points


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = a
    lon2, lat2 = b
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _path_lengths(points: list[tuple[float, float]]) -> list[float]:
    cumulative = [0.0]
    for a, b in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + _distance_km(a, b))
    return cumulative


def _point_at_distance(points: list[tuple[float, float]], cumulative: list[float], distance: float) -> tuple[float, float, float]:
    distance = max(0.0, min(distance, cumulative[-1]))
    for i in range(1, len(points)):
        if distance <= cumulative[i]:
            segment = max(cumulative[i] - cumulative[i - 1], 1e-12)
            ratio = (distance - cumulative[i - 1]) / segment
            lon = points[i - 1][0] + (points[i][0] - points[i - 1][0]) * ratio
            lat = points[i - 1][1] + (points[i][1] - points[i - 1][1]) * ratio
            heading = _bearing(points[i - 1], points[i])
            return lat, lon, heading
    return points[-1][1], points[-1][0], _bearing(points[-2], points[-1])


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dl = lon2 - lon1
    y = math.sin(dl) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


class GPSSimulatorService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._simulations: dict[uuid.UUID, SimulationState] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        *,
        user: User,
        vehicle_id: uuid.UUID,
        route_id: uuid.UUID,
        speed_multiplier: float,
    ) -> SimulationState:
        if self.settings.environment.lower() not in {"development", "test", "dev", "local", "demo"}:
            raise SimulatorError("GPS simulation is limited to isolated demonstration environments.")
        if self.settings.tracking_mode.lower() != "simulation":
            raise SimulatorError("TRACKING_MODE is not set to simulation.")
        if not 0.25 <= speed_multiplier <= 20:
            raise SimulatorError("Simulation speed must be between 0.25x and 20x.")

        db = SessionLocal()
        try:
            vehicle = db.get(Vehicle, vehicle_id)
            route = db.get(Route, route_id)
            if vehicle is None or route is None:
                raise SimulatorError("Vehicle or route not found.")
            if user.role not in (UserRole.ADMIN, UserRole.COLLECTOR):
                raise TrackingForbiddenError()
            if user.role == UserRole.COLLECTOR and vehicle.assigned_collector_id != user.id:
                raise TrackingForbiddenError()
            if route.vehicle_id != vehicle.id:
                raise SimulatorError("Selected route does not belong to the selected vehicle.")
            if route.status != RouteStatus.ACTIVE:
                raise SimulatorError("Start the route through the verified dispatch workflow before simulation.")
            points = _route_coordinates(route, db)

            tracking = TrackingRepository(db)
            session = tracking.get_active_for_vehicle(vehicle.id)
            if session is None or session.current_route_id != route.id or session.status != TrackingSessionStatus.ACTIVE:
                raise SimulatorError("An active tracking session for this route is required.")
            # Simulation only publishes DEMO telemetry and never changes the
            # authoritative route, vehicle or tracking lifecycle.

            simulation_id = uuid.uuid4()
            state = SimulationState(
                simulation_id=simulation_id,
                vehicle_id=vehicle.id,
                route_id=route.id,
                tracking_session_id=session.id,
                speed_multiplier=speed_multiplier,
                status="RUNNING",
                progress=0.0,
            )
            async with self._lock:
                # One active simulator per vehicle.
                for existing in list(self._simulations.values()):
                    if existing.vehicle_id == vehicle.id:
                        if existing.task:
                            existing.task.cancel()
                        self._simulations.pop(existing.simulation_id, None)
                state.task = asyncio.create_task(self._run(state, points))
                self._simulations[simulation_id] = state
            return state
        finally:
            db.close()

    async def _run(self, state: SimulationState, points: list[tuple[float, float]]) -> None:
        cumulative = _path_lengths(points)
        total = cumulative[-1]
        if total <= 0:
            await self._arrive_destination(state)
            return

        # Keep the simulated vehicle speed realistic; speed multiplier accelerates
        # simulation time rather than producing impossible GPS speeds.
        base_speed = min(35.0, max(5.0, self.settings.routing_average_speed_kmh))
        real_interval = max(0.25, float(self.settings.gps_update_interval_seconds) / state.speed_multiplier)
        simulated_interval = real_interval * state.speed_multiplier
        simulated_elapsed = 0.0
        previous_distance = 0.0
        last_position: tuple[float, float] | None = None
        revision_seen: tuple[int, int] | None = None
        virtual_elapsed_seconds = 0.0

        try:
            while state.progress < 1.0 and state.status != "STOPPED":
                if state.status == "PAUSED":
                    await asyncio.sleep(0.25)
                    continue
                # A cancellation updates the route in the same DB transaction.
                # Refresh simulated waypoints instead of continuing along a
                # stale polyline to a cancelled hospital. The simulator itself
                # still cannot certify any arrival or collection.
                db = SessionLocal()
                try:
                    live_route = db.get(Route, state.route_id)
                    live_session = db.get(TrackingSession, state.tracking_session_id)
                    if (live_route is None or live_route.status != RouteStatus.ACTIVE
                            or live_session is None
                            or live_session.current_route_id != state.route_id
                            or live_session.status != TrackingSessionStatus.ACTIVE):
                        state.status = "STOPPED"
                        return
                    info = live_route.optimization_details or {}
                    revision = (len(info.get('pickup_cancellations', [])),
                                len(info.get('reoptimizations', [])))
                    if revision_seen is None:
                        # A pickup might have been cancelled after start()
                        # loaded its path but before the task's first tick.
                        points = _route_coordinates(live_route, db)
                        cumulative = _path_lengths(points)
                        total = cumulative[-1]
                        revision_seen = revision
                    elif revision != revision_seen:
                        new_points = _route_coordinates(live_route, db)
                        if last_position is not None:
                            new_points[0] = last_position
                        points = new_points
                        cumulative = _path_lengths(points)
                        total = cumulative[-1]
                        simulated_elapsed = 0.0
                        previous_distance = 0.0
                        state.progress = 0.0
                        revision_seen = revision
                finally:
                    db.close()
                if total <= 0:
                    state.progress = 1.0
                    break
                distance = min(total, base_speed * simulated_elapsed / 3600.0)
                lat, lon, heading = _point_at_distance(points, cumulative, distance)
                now = datetime.now(timezone.utc) + timedelta(seconds=virtual_elapsed_seconds)

                db = SessionLocal()
                try:
                    user = UserRepository(db).get_by_id(
                        self._collector_id(db, state.vehicle_id)
                    )
                    if user is None:
                        raise SimulatorError("Assigned collector could not be loaded.")
                    location = TrackingService(db, self.settings).record_location(
                        user=user,
                        session_id=state.tracking_session_id,
                        data=GPSLocationCreate(
                            latitude=round(lat, 6),
                            longitude=round(lon, 6),
                            timestamp=now,
                            speed_kmh=base_speed if distance < total else 0,
                            heading_degrees=round(heading, 2),
                            accuracy_m=5,
                            source=LocationSource.SIMULATOR,
                        ),
                    )
                    topics = {vehicle_topic(location.vehicle_id)}
                    session = db.get(TrackingSession, location.tracking_session_id)
                    if session and session.current_route_id:
                        topics.add(route_topic(session.current_route_id))
                    event = {
                        "type": "location_update",
                        "event": "vehicle.location.updated",
                        "vehicle_id": str(location.vehicle_id),
                        "tracking_session_id": str(location.tracking_session_id),
                        "location": {
                            "id": str(location.id),
                            "latitude": float(location.latitude),
                            "longitude": float(location.longitude),
                            "timestamp": location.timestamp.isoformat(),
                            "speed_kmh": float(location.speed_kmh) if location.speed_kmh is not None else None,
                            "heading_degrees": float(location.heading_degrees) if location.heading_degrees is not None else None,
                            "accuracy_m": float(location.accuracy_m) if location.accuracy_m is not None else None,
                            "altitude_m": float(location.altitude_m) if location.altitude_m is not None else None,
                            "source": location.source.value,
                            "anomaly_type": location.anomaly_type.value if location.anomaly_type else None,
                        },
                        "route_progress": TrackingService(db, self.settings).get_route_progress(session.current_route_id)
                        if session and session.current_route_id else None,
                    }
                    await tracking_manager.broadcast(event, topics)
                finally:
                    db.close()

                state.progress = distance / total
                last_position = (lon, lat)
                await asyncio.sleep(real_interval)
                simulated_elapsed += simulated_interval
                virtual_elapsed_seconds += simulated_interval
                if distance == previous_distance and simulated_elapsed > 0:
                    simulated_elapsed += simulated_interval
                previous_distance = distance

            if state.status != "STOPPED":
                await self._arrive_destination(state)
        except asyncio.CancelledError:
            state.status = "STOPPED"
            raise
        except Exception:
            state.status = "ERROR"
            raise

    def _set_tracking_status(self, state: SimulationState, status: TrackingSessionStatus) -> None:
        # Simulator pause/resume must not pause a live driver's tracking session.
        return

    @staticmethod
    def _collector_id(db: Session, vehicle_id: uuid.UUID) -> uuid.UUID:
        vehicle = db.get(Vehicle, vehicle_id)
        if vehicle is None:
            raise SimulatorError("Vehicle not found.")
        return vehicle.assigned_collector_id

    async def _arrive_destination(self, state: SimulationState) -> None:
        """Preview simulated destination arrival; never certify physical arrival."""
        state.progress = 1.0
        state.status = "AT_DESTINATION"
        await tracking_manager.broadcast(
            {
                "type": "simulation_update",
                "event": "simulation.destination.preview",
                "vehicle_id": str(state.vehicle_id),
                "route_id": str(state.route_id),
                "status": "demo_at_destination",
                "verified_arrival": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            {vehicle_topic(state.vehicle_id), route_topic(state.route_id)},
        )

    async def pause(self, simulation_id: uuid.UUID, user: User) -> SimulationState:
        state = await self._get_authorized(simulation_id, user)
        if state.status == "RUNNING":
            self._set_tracking_status(state, TrackingSessionStatus.PAUSED)
            state.status = "PAUSED"
        return state

    async def resume(self, simulation_id: uuid.UUID, user: User) -> SimulationState:
        state = await self._get_authorized(simulation_id, user)
        if state.status == "AT_DESTINATION":
            return state
        if state.status == "COMPLETED":
            raise SimulatorError("Simulation is already complete.")
        self._set_tracking_status(state, TrackingSessionStatus.ACTIVE)
        state.status = "RUNNING"
        return state

    async def stop(self, simulation_id: uuid.UUID, user: User) -> SimulationState:
        state = await self._get_authorized(simulation_id, user)
        state.status = "STOPPED"
        if state.task and not state.task.done():
            state.task.cancel()
        return state

    async def reset(self, simulation_id: uuid.UUID, user: User) -> SimulationState:
        # Only rewind the simulator's own display state, never live tracking,
        # route stops, proof, vehicle availability or waste custody.
        state = await self.stop(simulation_id, user)
        state.progress = 0.0
        state.status = "RESET"
        return state

    async def _get(self, simulation_id: uuid.UUID) -> SimulationState:
        async with self._lock:
            state = self._simulations.get(simulation_id)
        if state is None:
            raise SimulatorError("Simulation not found.")
        return state

    async def _get_authorized(self, simulation_id: uuid.UUID, user: User) -> SimulationState:
        state = await self._get(simulation_id)
        db = SessionLocal()
        try:
            vehicle = db.get(Vehicle, state.vehicle_id)
            if vehicle is None:
                raise SimulatorError("Vehicle not found.")
            if user.role != UserRole.ADMIN and vehicle.assigned_collector_id != user.id:
                raise TrackingForbiddenError()
            return state
        finally:
            db.close()

    async def status(self, simulation_id: uuid.UUID, user: User) -> SimulationState:
        return await self._get_authorized(simulation_id, user)


gps_simulator = GPSSimulatorService(None)  # replaced lazily by get_simulator


def get_simulator(settings: Settings) -> GPSSimulatorService:
    global gps_simulator
    if gps_simulator.settings is None:
        gps_simulator.settings = settings
    return gps_simulator
