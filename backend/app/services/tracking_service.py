import uuid
import math
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.roles import UserRole
from app.models.route import Route, RouteStatus, RouteStop, RouteStopStatus, RouteDestinationState
from app.models.tracking import GPSDeviceNonce, TrackingLocation, TrackingSession, TrackingSessionStatus
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.pickup_request import PickupRequest
from app.models.waste_enums import PickupStatus, WasteEventType, WasteStatus
from app.repositories.pickup_repository import PickupRequestRepository
from app.repositories.tracking_repository import TrackingRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.tracking import GPSLocationCreate, TrackingSessionCreate
from app.services.gps_validation_service import GPSValidationError, GPSValidationService
from app.services.gps_device_provenance import VerifiedGPSMessage
from app.services.waste_event_service import WasteEventService


class TrackingNotFoundError(Exception):
    pass


class TrackingForbiddenError(Exception):
    pass


class ActiveTrackingSessionExistsError(Exception):
    pass


class ActiveRouteInProgressError(Exception):
    """The trip must be completed/cancelled by its own delivery workflow."""
    pass


class TrackingSessionAlreadyClosedError(Exception):
    pass


class TrackingService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings
        self.tracking = TrackingRepository(db)
        self.vehicles = VehicleRepository(db)
        self.pickups = PickupRequestRepository(db)
        self.validator = GPSValidationService(settings)
        self.events = WasteEventService(db)

    def _can_manage_vehicle(self, user: User, vehicle: Vehicle) -> bool:
        if user.role == UserRole.ADMIN:
            return True
        if user.role != UserRole.COLLECTOR:
            return False
        if vehicle.organization_id is None:
            return vehicle.assigned_collector_id == user.id
        from sqlalchemy import select
        from app.models.business import OrganizationMember
        role = self.db.scalar(select(OrganizationMember.member_role).where(
            OrganizationMember.organization_id == vehicle.organization_id,
            OrganizationMember.user_id == user.id, OrganizationMember.active.is_(True)).limit(1))
        return vehicle.assigned_collector_id == user.id and role in {'owner', 'manager', 'driver'}

    def _get_authorized_session(self, user: User, session_id: uuid.UUID) -> TrackingSession:
        session = self.tracking.get_session(session_id)
        if session is None:
            raise TrackingNotFoundError()
        vehicle = self.vehicles.get_by_id(session.vehicle_id)
        if vehicle is None or not self._can_manage_vehicle(user, vehicle):
            raise TrackingForbiddenError()
        return session

    def create_session(self, *, user: User, data: TrackingSessionCreate) -> TrackingSession:
        vehicle = self.vehicles.get_by_id(data.vehicle_id)
        if vehicle is None:
            raise TrackingNotFoundError()
        if not self._can_manage_vehicle(user, vehicle):
            raise TrackingForbiddenError()
        if data.pickup_id is not None:
            pickup = self.pickups.get_by_id(data.pickup_id)
            if pickup is None or pickup.assigned_vehicle_id != vehicle.id:
                raise TrackingForbiddenError()
            if user.role == UserRole.COLLECTOR and pickup.assigned_collector_id != user.id:
                raise TrackingForbiddenError()

        # Postgres row lock serializes requests from different app workers;
        # the DB partial-unique index is the final race-condition guard.
        self.db.scalar(select(Vehicle.id).where(Vehicle.id == vehicle.id).with_for_update(of=Vehicle))
        existing = self.tracking.get_active_for_vehicle(vehicle.id)
        if existing is not None:
            raise ActiveTrackingSessionExistsError()

        now = datetime.now(timezone.utc)
        session = TrackingSession(
            vehicle_id=vehicle.id,
            pickup_id=data.pickup_id,
            status=TrackingSessionStatus.ACTIVE,
            started_at=now,
        )
        try:
            return self.tracking.create_session(session)
        except IntegrityError as exc:
            self.db.rollback()
            # Never leak constraint details; preserve the API's existing 409.
            if 'uq_tracking_vehicle_open_session' in str(exc.orig).lower() or 'tracking_sessions.vehicle_id' in str(exc.orig).lower():
                raise ActiveTrackingSessionExistsError() from exc
            raise

    def record_location(self, *, user: User, session_id: uuid.UUID, data: GPSLocationCreate,
                        verified_device: VerifiedGPSMessage | None = None) -> TrackingLocation:
        session = self._get_authorized_session(user, session_id)
        if session.status not in (TrackingSessionStatus.ACTIVE, TrackingSessionStatus.PAUSED):
            raise TrackingForbiddenError()

        self.validator.validate(
            latitude=data.latitude, longitude=data.longitude, speed_kmh=data.speed_kmh
        )
        # Use the authenticated, anomaly-free track as the *only* progression
        # baseline for a signed point. Unverified map reports are not evidence.
        previous = self.tracking.get_latest_location_for_session(
            session.id, trusted_only=verified_device is not None,
        )
        anomaly = self.validator.classify_against_previous(
            current_timestamp=data.timestamp,
            latitude=data.latitude,
            longitude=data.longitude,
            speed_kmh=data.speed_kmh,
            previous=previous,
        )

        # A location report is not a geofence proof by itself. Clock skew,
        # spoof-like jumps, stale/poor-accuracy points and demo inputs must
        # never advance a live delivery state machine.
        now = datetime.now(timezone.utc)
        clock_delta = (data.timestamp.astimezone(timezone.utc) - now).total_seconds()
        reliable_for_progress = (
            session.status == TrackingSessionStatus.ACTIVE
            and verified_device is not None
            and data.source.value in {"gps_device", "mobile_app"}
            and anomaly is None
            and -90 <= clock_delta <= 30
            and data.accuracy_m is not None
            and 0 <= float(data.accuracy_m) <= 100
        )
        if data.source.value == "simulator" and self.settings.environment.lower() not in {"development", "test", "dev", "local", "demo"}:
            raise GPSValidationError("Simulator source is permitted only in demo/test environments.")
        if data.source.value == "manual" and self.settings.environment.lower() not in {"development", "test", "dev", "local", "demo"}:
            raise GPSValidationError("Manual coordinates cannot be submitted as production device telemetry.")

        location = TrackingLocation(
            tracking_session_id=session.id,
            vehicle_id=session.vehicle_id,
            latitude=data.latitude,
            longitude=data.longitude,
            timestamp=data.timestamp,
            speed_kmh=data.speed_kmh,
            heading_degrees=data.heading_degrees,
            accuracy_m=data.accuracy_m,
            altitude_m=data.altitude_m,
            source=data.source,
            provenance_verified=verified_device is not None,
            anomaly_type=anomaly,
        )
        pending_broadcasts: list[tuple[dict, set[str]]] = []
        try:
            if verified_device is not None:
                # Replay nonce, GPS record, session position and route-state
                # transition share ONE transaction. A failed progression must
                # not burn a valid nonce or leave a phantom GPS sample.
                self.db.add(GPSDeviceNonce(
                    device_id=verified_device.device_id,
                    nonce=verified_device.nonce,
                    tracking_session_id=session.id,
                ))
                try:
                    self.db.flush()
                except IntegrityError as exc:
                    self.db.rollback()
                    raise GPSValidationError("Repeated GPS device nonce.") from exc

            saved = self.tracking.create_location(location, commit=False)
            previous_time = previous.timestamp if previous is not None else None
            if previous_time is not None and (
                previous_time.tzinfo is None or previous_time.utcoffset() is None
            ):
                previous_time = previous_time.replace(tzinfo=timezone.utc)
            if previous_time is None or data.timestamp > previous_time:
                session.last_location_at = data.timestamp
            # No tracking_repository.save_session() here: that method commits
            # immediately, splitting the transaction and consuming the nonce.
            self.db.add(session)
            if reliable_for_progress:
                pending_broadcasts = self._advance_route_progress(
                    session, data.latitude, data.longitude, commit=False
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        # Publish only committed state. A failed broadcast must not turn an
        # already successful GPS request into an apparent transaction failure.
        from app.realtime.tracking_manager import tracking_manager
        for event, topics in pending_broadcasts:
            try:
                tracking_manager.broadcast_from_sync(event, topics)
            except Exception:
                # WebSocket fan-out is best-effort; persisted state is canonical.
                import logging
                logging.getLogger(__name__).exception(
                    "Failed to publish committed route-progress event"
                )
        return saved

    @staticmethod
    def _distance_km(latitude_a, longitude_a, latitude_b, longitude_b) -> float:
        radius = 6371.0088
        lat_a, lat_b = math.radians(float(latitude_a)), math.radians(float(latitude_b))
        d_lat = lat_b - lat_a
        d_lon = math.radians(float(longitude_b) - float(longitude_a))
        value = math.sin(d_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(d_lon / 2) ** 2
        return radius * 2 * math.asin(math.sqrt(max(0.0, min(1.0, value))))

    def _advance_route_progress(
        self, session: TrackingSession, latitude, longitude, *, commit: bool = True
    ) -> list[tuple[dict, set[str]]]:
        if session.current_route_id is None:
            return []
        route = self.db.get(Route, session.current_route_id)
        if route is None or route.status != RouteStatus.ACTIVE:
            return []
        # Buffer notifications until the route-state transaction commits. Never
        # publish a state transition which the database may still roll back.
        pending_broadcasts: list[tuple[dict, set[str]]] = []
        stops = list(self.db.scalars(
            select(RouteStop).where(RouteStop.route_id == route.id).order_by(RouteStop.sequence)
        ).all())
        current = next((stop for stop in stops if stop.status in {RouteStopStatus.EN_ROUTE, RouteStopStatus.ARRIVED}), None)
        if current is None:
            current = next((stop for stop in stops if stop.status == RouteStopStatus.PENDING), None)
            if current is not None:
                current.status = RouteStopStatus.EN_ROUTE

        now = datetime.now(timezone.utc)
        if current is not None and current.status == RouteStopStatus.EN_ROUTE:
            distance = self._distance_km(latitude, longitude, current.latitude, current.longitude)
            if distance <= self.settings.route_stop_arrival_radius_km:
                current.status = RouteStopStatus.ARRIVED
                current.arrived_at = current.arrived_at or now

        all_collected = bool(stops) and all(
            stop.status in {RouteStopStatus.COLLECTED, RouteStopStatus.SKIPPED, RouteStopStatus.CANCELLED}
            for stop in stops
        )
        if all_collected and route.destination_state == RouteDestinationState.COLLECTION.value:
            route.destination_state = RouteDestinationState.EN_ROUTE_TO_DESTINATION.value

        # The first GPS update after the last hospital collection starts the
        # destination transport leg. This is deliberately separate from the
        # collection response so the hospital can observe COLLECTED first.
        if all_collected and route.destination_state == RouteDestinationState.EN_ROUTE_TO_DESTINATION.value:
            for stop in stops:
                pickup = self.db.get(PickupRequest, stop.pickup_id)
                if pickup is None:
                    continue
                if pickup.status == PickupStatus.COLLECTED:
                    pickup.status = PickupStatus.IN_TRANSIT
                    for item in pickup.items:
                        if item.waste_record.status == WasteStatus.COLLECTED:
                            item.waste_record.status = WasteStatus.IN_TRANSIT
                            self.events.record(
                                waste_record_id=item.waste_record_id,
                                event_type=WasteEventType.IN_TRANSIT,
                                status_snapshot=WasteStatus.IN_TRANSIT,
                                actor_user_id=pickup.assigned_collector_id,
                                quantity=item.waste_record.quantity,
                                notes="Transport leg started toward the confirmed Waste Processing Facility.",
                                metadata={"route_id": str(route.id)},
                                commit=False,
                            )
                            from app.realtime.tracking_manager import route_topic, vehicle_topic
                            pending_broadcasts.append((
                                {
                                    "type": "status_update",
                                    "event": "pickup.status.updated",
                                    "pickup_id": str(pickup.id),
                                    "waste_record_ids": [str(x.waste_record_id) for x in pickup.items],
                                    "pickup_status": pickup.status.value,
                                    "waste_status": WasteStatus.IN_TRANSIT.value,
                                    "vehicle_id": str(session.vehicle_id),
                                    "route_id": str(route.id),
                                    "timestamp": now.isoformat(),
                                },
                                {route_topic(route.id), vehicle_topic(session.vehicle_id)},
                            ))

        if all_collected and route.destination_latitude is not None and route.destination_longitude is not None:
            distance = self._distance_km(
                latitude, longitude, route.destination_latitude, route.destination_longitude
            )
            if distance <= self.settings.route_stop_arrival_radius_km and route.destination_state != RouteDestinationState.AT_DESTINATION.value:
                route.destination_state = RouteDestinationState.AT_DESTINATION.value
                route.destination_arrived_at = route.destination_arrived_at or now

                from app.realtime.tracking_manager import route_topic, vehicle_topic
                pending_broadcasts.append((
                    {
                        "type": "status_update",
                        "event": "vehicle.destination.arrived",
                        "vehicle_id": str(session.vehicle_id),
                        "tracking_session_id": str(session.id),
                        "route_id": str(route.id),
                        "facility_id": self._route_facility_id(route.id),
                        "timestamp": now.isoformat(),
                        "latitude": float(latitude),
                        "longitude": float(longitude),
                        "distance_to_destination": float(distance),
                    },
                    {vehicle_topic(session.vehicle_id), route_topic(route.id)},
                ))
        if commit:
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            from app.realtime.tracking_manager import tracking_manager
            for event, topics in pending_broadcasts:
                tracking_manager.broadcast_from_sync(event, topics)
        return pending_broadcasts

    def _route_facility_id(self, route_id: uuid.UUID) -> str | None:
        from app.models.matching_record import MatchingRecord
        from app.models.pickup_request import PickupRequestItem
        stops = self.db.scalars(select(RouteStop).where(RouteStop.route_id == route_id)).all()
        for stop in stops:
            item = self.db.scalar(select(PickupRequestItem).where(PickupRequestItem.pickup_request_id == stop.pickup_id))
            if item:
                match = self.db.scalar(select(MatchingRecord).where(
                    MatchingRecord.waste_record_id == item.waste_record_id,
                    MatchingRecord.is_confirmed.is_(True),
                ))
                if match and match.confirmed_facility_id:
                    return str(match.confirmed_facility_id)
        return None

    def get_route_progress(self, route_id: uuid.UUID) -> dict | None:
        route = self.db.get(Route, route_id)
        if route is None:
            return None
        stops = list(self.db.scalars(
            select(RouteStop).where(RouteStop.route_id == route.id).order_by(RouteStop.sequence)
        ).all())
        completed_statuses = {RouteStopStatus.COLLECTED, RouteStopStatus.SKIPPED, RouteStopStatus.CANCELLED}
        completed = [stop for stop in stops if stop.status in completed_statuses]
        current = next((stop for stop in stops if stop.status in {RouteStopStatus.EN_ROUTE, RouteStopStatus.ARRIVED}), None)
        next_stop = next((stop for stop in stops if stop.status == RouteStopStatus.PENDING), None)
        return {
            "route_id": str(route.id),
            "status": route.status.value if hasattr(route.status, "value") else str(route.status),
            "destination_state": route.destination_state,
            "destination_arrived_at": route.destination_arrived_at.isoformat() if route.destination_arrived_at else None,
            "destination_received_at": route.destination_received_at.isoformat() if route.destination_received_at else None,
            "completed_stops": len(completed),
            "total_stops": len(stops),
            "current_stop_id": str(current.id) if current else None,
            "next_stop_id": str(next_stop.id) if next_stop else None,
            "stops": [{"id": str(stop.id), "status": stop.status.value} for stop in stops],
        }

    def get_latest_location(self, *, user: User, vehicle_id: uuid.UUID) -> TrackingLocation | None:
        vehicle = self.vehicles.get_by_id(vehicle_id)
        if vehicle is None:
            raise TrackingNotFoundError()
        from app.realtime.tracking_authorization import can_view_vehicle
        if not can_view_vehicle(self.db, user, vehicle_id):
            raise TrackingForbiddenError()
        return self.tracking.get_latest_location(vehicle_id)

    def complete_session(self, *, user: User, session_id: uuid.UUID) -> TrackingSession:
        session = self._get_authorized_session(user, session_id)
        # Route.start() takes the same vehicle lock before making its ACTIVE
        # transition. This closes the completion-vs-start race across workers.
        self.db.scalar(select(Vehicle.id).where(Vehicle.id == session.vehicle_id).with_for_update(of=Vehicle))
        session = self.db.scalar(select(TrackingSession).where(
            TrackingSession.id == session_id).with_for_update(of=TrackingSession))
        if session is None:
            raise TrackingNotFoundError()
        # Look up by vehicle, not just current_route_id: a stale/missing link
        # must never permit live tracking to be terminated under an ACTIVE trip.
        active_route = self.db.scalar(select(Route.id).where(
            Route.vehicle_id == session.vehicle_id,
            Route.status == RouteStatus.ACTIVE,
        ).limit(1))
        if active_route is not None:
            raise ActiveRouteInProgressError(
                "Complete or cancel the active delivery route before ending GPS tracking."
            )
        if session.status == TrackingSessionStatus.COMPLETED:
            return session  # repeated command is harmless
        if session.status == TrackingSessionStatus.CANCELLED:
            raise TrackingSessionAlreadyClosedError("Cancelled tracking sessions cannot be completed.")
        session.status = TrackingSessionStatus.COMPLETED
        session.ended_at = datetime.now(timezone.utc)
        session.current_route_id = None
        return self.tracking.save_session(session)
