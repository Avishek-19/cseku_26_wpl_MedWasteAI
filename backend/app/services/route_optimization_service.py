"""Route optimization service for multi-stop medical waste collection.

The optimizer is deliberately separated from HTTP/UI code. It supports an
OSRM-compatible routing backend when configured/available and falls back to a
deterministic Haversine model for development/offline operation.
"""
from __future__ import annotations

import hashlib
import json
import math
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.hospital_profile import HospitalProfile
from app.models.pickup_request import PickupRequest
from app.models.route import Route, RouteStatus, RouteStop, RouteStopStatus, RouteDestinationState
from app.models.tracking import TrackingLocation, TrackingSession, TrackingSessionStatus
from app.models.user import User
from app.models.business import OrganizationMember
from app.services.organization_context import selected_org_id
from app.models.vehicle import Vehicle
from app.models.waste_enums import PickupPriority, PickupStatus, VehicleStatus
from app.repositories.route_repository import RouteRepository
from app.repositories.tracking_repository import TrackingRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.matching_repository import MatchingRepository
from app.services.quantity_service import quantity_to_kg


@dataclass(frozen=True)
class Point:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class StopCandidate:
    pickup: PickupRequest
    point: Point
    weight_kg: float
    priority: PickupPriority
    requested_at: datetime | None
    requested_end_at: datetime | None = None


@dataclass(frozen=True)
class RoutePlan:
    ordered: list[StopCandidate]
    total_distance_km: float
    duration_minutes: int
    geometry: dict | None
    provider: str
    explanation: list[str]


class RouteOptimizationError(Exception):
    pass


class RouteForbiddenError(RouteOptimizationError):
    pass


class RouteValidationError(RouteOptimizationError):
    pass


class RouteProvider:
    name = "base"

    def matrix(self, points: list[Point]) -> list[list[float]]:
        raise NotImplementedError

    def route(self, points: list[Point]) -> tuple[float, int, dict | None]:
        raise NotImplementedError


class HaversineRoutingProvider(RouteProvider):
    name = "haversine"

    def __init__(self, average_speed_kmh: float):
        self.average_speed_kmh = max(1.0, average_speed_kmh)

    @staticmethod
    def distance(a: Point, b: Point) -> float:
        radius = 6371.0088
        lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
        dlat = lat2 - lat1
        dlon = math.radians(b.longitude - a.longitude)
        h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return radius * 2 * math.asin(math.sqrt(h))

    def matrix(self, points: list[Point]) -> list[list[float]]:
        return [[0.0 if i == j else self.distance(a, b) for j, b in enumerate(points)] for i, a in enumerate(points)]

    def route(self, points: list[Point]) -> tuple[float, int, dict | None]:
        distance = sum(self.distance(points[i], points[i + 1]) for i in range(len(points) - 1))
        minutes = math.ceil(distance / self.average_speed_kmh * 60)
        return distance, minutes, None


class OSRMRoutingProvider(RouteProvider):
    name = "osrm"

    def __init__(self, base_url: str, timeout: float, fallback: HaversineRoutingProvider):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.fallback = fallback

    def _get_json(self, path: str, params: dict) -> dict:
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "MedWaste-AI/1.0"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _coords(points: list[Point]) -> str:
        return ";".join(f"{p.longitude:.6f},{p.latitude:.6f}" for p in points)

    def matrix(self, points: list[Point]) -> list[list[float]]:
        data = self._get_json("/table/v1/driving/" + self._coords(points), {"annotations": "distance"})
        if data.get("code") != "Ok":
            raise RuntimeError(data.get("message", "Routing matrix failed"))
        matrix = data.get("distances")
        if matrix is None or len(matrix) != len(points):
            raise RuntimeError("OSRM returned an incomplete routing matrix")
        result = []
        for row in matrix:
            if len(row) != len(points) or any(v is None or not math.isfinite(float(v)) or float(v) < 0 for v in row):
                raise RuntimeError("OSRM reports an unreachable stop; cannot treat it as zero distance")
            result.append([float(v) / 1000.0 for v in row])
        return result

    def route(self, points: list[Point]) -> tuple[float, int, dict | None]:
        data = self._get_json(
            "/route/v1/driving/" + self._coords(points),
            {"overview": "full", "geometries": "geojson", "steps": "false"},
        )
        if data.get("code") != "Ok" or not data.get("routes"):
            raise RuntimeError(data.get("message", "Routing request failed"))
        route = data["routes"][0]
        return (
            float(route["distance"]) / 1000.0,
            math.ceil(float(route["duration"]) / 60),
            route.get("geometry"),
        )


class RouteOptimizationService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings
        self.routes = RouteRepository(db)
        self.tracking = TrackingRepository(db)
        self.vehicles = VehicleRepository(db)
        self.matches = MatchingRepository(db)

    def _providers(self) -> tuple[RouteProvider, RouteProvider]:
        fallback = HaversineRoutingProvider(self.settings.routing_average_speed_kmh)
        if self.settings.routing_provider.lower() in {"auto", "osrm"}:
            return OSRMRoutingProvider(
                self.settings.routing_base_url,
                self.settings.routing_timeout_seconds,
                fallback,
            ), fallback
        return fallback, fallback

    def _can_manage(self, user: User, vehicle: Vehicle) -> bool:
        if user.role.value == 'admin':
            return True
        if user.role.value != 'collector':
            return False
        if vehicle.organization_id is None:
            # Preserve existing standalone development vehicles.
            return selected_org_id() is None and vehicle.assigned_collector_id == user.id
        if selected_org_id() is not None and selected_org_id() != vehicle.organization_id:
            return False
        role = self.db.scalar(select(OrganizationMember.member_role).where(
            OrganizationMember.organization_id == vehicle.organization_id,
            OrganizationMember.user_id == user.id,
            OrganizationMember.active.is_(True)).limit(1))
        return role in {'owner', 'manager', 'dispatcher'} or (
            role == 'driver' and vehicle.assigned_collector_id == user.id)

    def _get_pickups(self, vehicle: Vehicle, pickup_ids: list[uuid.UUID]) -> list[PickupRequest]:
        rows = list(self.db.execute(
            select(PickupRequest).where(PickupRequest.id.in_(pickup_ids))
        ).scalars().unique().all())
        by_id = {p.id: p for p in rows}
        missing = [str(i) for i in pickup_ids if i not in by_id]
        if missing:
            raise RouteValidationError(f"Pickup(s) not found: {', '.join(missing)}")
        for p in rows:
            if p.assigned_vehicle_id != vehicle.id or p.assigned_collector_id != vehicle.assigned_collector_id:
                raise RouteForbiddenError("All pickups must be assigned to the selected vehicle and its collector.")
            if p.status not in {PickupStatus.ASSIGNED, PickupStatus.COLLECTED, PickupStatus.IN_TRANSIT}:
                raise RouteValidationError(f"Pickup {p.id} is not route-eligible in its current status.")
        return [by_id[i] for i in pickup_ids]

    def _require_complete_assigned_pickup_set(self, vehicle_id: uuid.UUID, pickup_ids: list[uuid.UUID]) -> None:
        """Planning contract: a dispatchable route contains ALL assigned pickups.

        If a subset is optimized, the old confirm() check would reject it only
        after a draft had been created. Fail before touching a saved route.
        """
        assigned_ids = set(self.db.scalars(select(PickupRequest.id).where(
            PickupRequest.assigned_vehicle_id == vehicle_id,
            PickupRequest.status == PickupStatus.ASSIGNED,
        )).all())
        if assigned_ids != set(pickup_ids):
            raise RouteValidationError(
                "Select every ASSIGNED pickup for this vehicle before optimizing. "
                "Refresh assignments and resolve ineligible pickups; partial trips are not supported."
            )

    def _facility_for_pickup(self, pickup: PickupRequest) -> TreatmentFacilityProfile | None:
        facility_ids = set()
        for item in pickup.items:
            match = self.matches.get_confirmed_for_record(item.waste_record_id)
            if match and match.confirmed_facility_id:
                facility_ids.add(match.confirmed_facility_id)
        if len(facility_ids) > 1:
            raise RouteValidationError(f"Pickup {pickup.id} has multiple confirmed destinations.")
        if not facility_ids:
            return None
        return self.db.get(TreatmentFacilityProfile, next(iter(facility_ids)))

    def _weight(self, pickup: PickupRequest) -> float:
        total = Decimal("0")
        for item in pickup.items:
            kg = quantity_to_kg(item.waste_record.quantity, item.waste_record.unit)
            if kg is None:
                raise RouteValidationError(f"Pickup {pickup.id} has an unconvertible waste quantity.")
            total += kg
        return float(total)

    def _stop_point(self, pickup: PickupRequest, explicit: dict[uuid.UUID, Point]) -> Point:
        hospital = self.db.get(HospitalProfile, pickup.hospital_id)
        if hospital and hospital.latitude is not None and hospital.longitude is not None:
            authoritative = Point(float(hospital.latitude), float(hospital.longitude))
            if pickup.id in explicit and HaversineRoutingProvider.distance(authoritative, explicit[pickup.id]) > 0.25:
                raise RouteValidationError("Stop coordinates differ from the hospital's verified location.")
            return authoritative
        if pickup.id in explicit:
            # Development/demo-only fallback. A collector-supplied coordinate
            # must never become the trusted arrival geofence in live operation.
            if self.settings.environment.lower() not in {'development', 'test'}:
                raise RouteValidationError("Save the hospital's verified location before routing this pickup.")
            return explicit[pickup.id]
        raise RouteValidationError(
            f"Pickup {pickup.id} has no coordinates. Geocode/save the hospital coordinates "
            "or provide stop_coordinates in the optimization request."
        )

    def _origin(
        self,
        vehicle_id: uuid.UUID,
        latitude: Decimal | None,
        longitude: Decimal | None,
        fallback: Point | None = None,
    ) -> Point:
        if latitude is not None and longitude is not None:
            return Point(float(latitude), float(longitude))
        latest = self.tracking.get_latest_location(vehicle_id)
        if latest:
            return Point(float(latest.latitude), float(latest.longitude))
        if fallback is not None:
            # Legacy vehicle records do not persist a coordinate. Using the
            # first selected hospital as a deterministic origin keeps the
            # planner usable during rollout without inventing coordinates.
            return fallback
        raise RouteValidationError(
            "Route origin is missing. Provide origin coordinates or start GPS tracking first."
        )

    def _destination(
        self,
        pickups: list[PickupRequest],
        latitude: Decimal | None,
        longitude: Decimal | None,
    ) -> Point:
        facilities = []
        for pickup in pickups:
            facility = self._facility_for_pickup(pickup)
            if facility:
                facilities.append(facility)
        ids = {f.id for f in facilities}
        if len(ids) > 1:
            raise RouteValidationError(
                "Selected pickups resolve to different treatment facilities. "
                "Optimize separate routes so every transport has one authoritative destination."
            )
        if not facilities:
            raise RouteValidationError("Every route pickup must have a confirmed Treatment Facility destination.")

        # Issue 5: a client-supplied coordinate can never define the delivery
        # geofence. A confirmed facility is not dispatchable until its profile
        # has both persisted, geographically valid WGS84 coordinates.
        facility = facilities[0]
        if facility.latitude is None or facility.longitude is None:
            raise RouteValidationError(
                "Confirmed Treatment Facility has no saved location. "
                "Save its latitude AND longitude on the facility profile before route planning or dispatch."
            )
        authoritative = Point(float(facility.latitude), float(facility.longitude))
        if (not math.isfinite(authoritative.latitude) or
                not math.isfinite(authoritative.longitude) or
                not -90 <= authoritative.latitude <= 90 or
                not -180 <= authoritative.longitude <= 180):
            raise RouteValidationError("Confirmed Treatment Facility has invalid saved GPS coordinates.")
        if (latitude is None) != (longitude is None):
            raise RouteValidationError("Provide both destination latitude and longitude, or neither.")
        if latitude is not None:
            supplied = Point(float(latitude), float(longitude))
            if (not math.isfinite(supplied.latitude) or not math.isfinite(supplied.longitude) or
                    not -90 <= supplied.latitude <= 90 or not -180 <= supplied.longitude <= 180):
                raise RouteValidationError("Explicit destination coordinates are invalid.")
            if HaversineRoutingProvider.distance(authoritative, supplied) > 0.25:
                raise RouteValidationError(
                    "Explicit destination coordinates do not match the confirmed Treatment Facility."
                )
        # Always persist the profile's coordinates; never trust a supplied
        # fallback even in development/demo or a previously saved draft.
        return authoritative

    def _require_current_route_destination(self, route: Route, pickups: list[PickupRequest]) -> Point:
        """Do not dispatch using old geometry after a facility profile moves.

        Planning accepts a nearby caller coordinate but stores the authoritative
        profile location; a *persisted* route must exactly match that profile.
        """
        verified = self._destination(pickups, None, None)
        if (route.destination_latitude is None or route.destination_longitude is None or
                round(float(route.destination_latitude), 6) != round(verified.latitude, 6) or
                round(float(route.destination_longitude), 6) != round(verified.longitude, 6)):
            raise RouteValidationError(
                "Confirmed Treatment Facility location changed after route planning. "
                "Reoptimize using the facility's latest verified coordinates."
            )
        return verified

    def _validate_dispatch_destination(self, pickups: list[PickupRequest]) -> None:
        """Prevent dispatch to a suspended, expired or incompatible confirmed facility.

        Capacity was reserved at confirmation; do not require *another* full
        capacity allocation at dispatch, which would double count this load.
        """
        from app.services.organization_eligibility import eligible_facility
        from app.models.user import User
        for pickup in pickups:
            for item in pickup.items:
                match = self.matches.get_confirmed_for_record(item.waste_record_id)
                if match is None or not match.is_confirmed or not match.confirmed_facility_id:
                    raise RouteValidationError("Facility confirmation was removed. Re-match and reoptimize.")
                facility = self.db.get(TreatmentFacilityProfile, match.confirmed_facility_id)
                owner = self.db.get(User, facility.user_id) if facility else None
                method = next((str(c.get('processing_method')) for c in (match.candidates or [])
                               if str(c.get('id')) == str(match.confirmed_facility_id)
                               and c.get('processing_method')), match.processing_method)
                if not method or not owner or not owner.is_active or not eligible_facility(
                    self.db, facility, need_capability=method, new_work=True
                ):
                    raise RouteValidationError(
                        "Confirmed facility is no longer authorized, available or capable. "
                        "Re-match the affected waste and reoptimize the route."
                    )
                # A facility may stop accepting a waste category after the
                # original match; its old reservation alone is not authority
                # to deliver medically incompatible waste.
                from app.models.facility_accepted_category import FacilityAcceptedCategory
                accepted = self.db.scalar(select(FacilityAcceptedCategory.id).where(
                    FacilityAcceptedCategory.facility_id == facility.id,
                    FacilityAcceptedCategory.category_id == item.waste_record.category_id
                ).limit(1))
                if accepted is None:
                    raise RouteValidationError(
                        "Confirmed facility no longer accepts the waste category. Re-match and reoptimize."
                    )
                if float(facility.current_utilization_kg) > float(facility.capacity_kg):
                    raise RouteValidationError("Confirmed facility capacity is exceeded. Re-match and reoptimize.")

    @staticmethod
    def _utc(value: datetime) -> datetime:
        # PostgreSQL returns aware timestamps; SQLite test databases may return
        # naive values for DateTime(timezone=True). Treat naive stored values as
        # UTC consistently rather than comparing naive and aware datetimes.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @classmethod
    def _validate_arrival(cls, candidate: StopCandidate, arrival: datetime) -> None:
        start = cls._utc(candidate.requested_at) if candidate.requested_at else None
        end = cls._utc(candidate.requested_end_at) if candidate.requested_end_at else None
        if start is not None and end is not None and end < start:
            raise RouteValidationError(
                f"Pickup {candidate.pickup.id} has an invalid pickup window (end before start)."
            )
        if end is not None and arrival > end:
            raise RouteValidationError(
                f"Pickup {candidate.pickup.id} cannot meet the requested pickup window: "
                f"ETA {arrival.isoformat()} is later than the deadline {end.isoformat()}. "
                "Adjust the pickup window, departure time or route selection and reoptimize."
            )

    @classmethod
    def _schedule_arrivals(
        cls, ordered: list[StopCandidate], origin: Point, start_at: datetime, provider: RouteProvider,
    ) -> tuple[list[datetime], datetime]:
        """Use provider travel times, plus waiting, for each authoritative ETA.

        This runs before database mutations for both draft and live replanning.
        An end-only window is also enforced; exact deadline equality is allowed.
        """
        cursor, previous_point = cls._utc(start_at), origin
        arrivals: list[datetime] = []
        for candidate in ordered:
            _, travel_minutes, _ = provider.route([previous_point, candidate.point])
            cursor += timedelta(minutes=travel_minutes)
            if candidate.requested_at is not None:
                earliest = cls._utc(candidate.requested_at)
                if cursor < earliest:
                    cursor = earliest
            cls._validate_arrival(candidate, cursor)
            arrivals.append(cursor)
            previous_point = candidate.point
        return arrivals, cursor

    @classmethod
    def _validate_existing_windows(
        cls, stops: list[RouteStop], pickups: list[PickupRequest], *,
        route: Route | None = None, now: datetime | None = None,
    ) -> None:
        """A cached or approved route cannot bypass updated pickup deadlines."""
        by_id = {pickup.id: pickup for pickup in pickups}
        current = cls._utc(now or datetime.now(timezone.utc))
        # Route ETA calculated before a delayed departure is optimistic. Treat
        # all minutes of departure delay as travel delay (conservative when
        # there is waiting at an early stop). This lets confirm/start reject an
        # infeasible route without making dozens of OSRM calls on dispatch.
        departure_delay = timedelta()
        if route is not None and any(p.requested_pickup_end_at for p in pickups):
            planned_start = (route.optimization_details or {}).get("planned_start_at")
            if not planned_start:
                raise RouteValidationError(
                    "Route was planned without verified pickup deadlines. Reoptimize before dispatch."
                )
            try:
                original_departure = cls._utc(datetime.fromisoformat(planned_start))
            except (TypeError, ValueError):
                raise RouteValidationError("Route has an invalid planned departure time. Reoptimize.") from None
            departure_delay = max(timedelta(), current - original_departure)
        for stop in stops:
            pickup = by_id[stop.pickup_id]
            if pickup.requested_pickup_end_at is None and pickup.requested_pickup_at is None:
                continue
            end = cls._utc(pickup.requested_pickup_end_at) if pickup.requested_pickup_end_at else None
            if end is not None and current > end:
                raise RouteValidationError(
                    f"Pickup {pickup.id} deadline has passed. Replan or reschedule the pickup."
                )
            if stop.estimated_arrival_at is None:
                raise RouteValidationError("Route has no estimated stop arrival. Reoptimize this route.")
            estimated = cls._utc(stop.estimated_arrival_at)
            start = cls._utc(pickup.requested_pickup_at) if pickup.requested_pickup_at else None
            if start is not None and end is not None and end < start:
                raise RouteValidationError(f"Pickup {pickup.id} has an invalid pickup window.")
            if start is not None and estimated < start:
                raise RouteValidationError(f"Pickup {pickup.id} ETA precedes its pickup window. Reoptimize.")
            if end is not None and estimated + departure_delay > end:
                raise RouteValidationError(
                    f"Pickup {pickup.id} ETA exceeds its pickup deadline after departure delay. Reoptimize."
                )

    @staticmethod
    def _two_opt(order: list[int], matrix: list[list[float]], candidates: list[StopCandidate]) -> list[int]:
        best = order[:]

        def cost(seq: list[int]) -> float:
            return sum(matrix[seq[k]][seq[k + 1]] for k in range(len(seq) - 1))

        def valid(seq: list[int]) -> bool:
            pickups = [candidates[i - 1] for i in seq if 1 <= i <= len(candidates)]
            ranks = {PickupPriority.EMERGENCY: 0, PickupPriority.URGENT: 1, PickupPriority.NORMAL: 2}
            priority_ranks = [ranks[p.priority] for p in pickups]
            # Never move a lower-priority pickup ahead of a higher-priority one.
            if priority_ranks != sorted(priority_ranks):
                return False
            # Preserve the original release-time ordering for routes without
            # hard deadlines; deadline-bound routes skip distance-only 2-opt.
            for left, right in zip(pickups, pickups[1:]):
                if left.priority == right.priority and left.requested_at and right.requested_at:
                    if RouteOptimizationService._utc(left.requested_at) > RouteOptimizationService._utc(right.requested_at):
                        return False
            return True

        improved = True
        while improved:
            improved = False
            for i in range(1, len(best) - 2):
                for j in range(i + 1, len(best)):
                    candidate = best[:i] + best[i:j][::-1] + best[j:]
                    if valid(candidate) and cost(candidate) + 1e-9 < cost(best):
                        best = candidate
                        improved = True
        return best

    def _optimize_order(
        self,
        candidates: list[StopCandidate],
        origin: Point,
        destination: Point,
        provider: RouteProvider,
    ) -> list[StopCandidate]:
        # Nodes: origin, pickups, destination.
        points = [origin] + [c.point for c in candidates] + [destination]
        matrix = provider.matrix(points)
        n = len(candidates)

        # Priority remains the first dispatch rule. Within the same priority,
        # end-of-window deadlines come before unbounded requests so time-critical
        # stops are not postponed behind flexible ones.
        unvisited = set(range(1, n + 1))
        order = [0]
        while unvisited:
            current = order[-1]
            best = min(
                unvisited,
                key=lambda idx: (
                    0 if candidates[idx - 1].priority == PickupPriority.EMERGENCY else
                    1 if candidates[idx - 1].priority == PickupPriority.URGENT else 2,
                    self._utc(candidates[idx - 1].requested_end_at).timestamp()
                    if candidates[idx - 1].requested_end_at is not None else float("inf"),
                    self._utc(candidates[idx - 1].requested_at).timestamp()
                    if candidates[idx - 1].requested_at is not None else float("inf"),
                    matrix[current][idx],
                ),
            )
            order.append(best)
            unvisited.remove(best)

        # Distance-only 2-opt can move a deadline-bound stop after its latest
        # time without noticing. Keep earliest-deadline order for such routes;
        # the provider's actual travel-time schedule is still validated below.
        if any(c.requested_end_at is not None for c in candidates):
            pickup_indices = order[1:]
        else:
            improved = self._two_opt(order + [n + 1], matrix, candidates)
            pickup_indices = improved[1:-1]
        return [candidates[i - 1] for i in pickup_indices]

    def optimize(
        self,
        *,
        user: User,
        vehicle_id: uuid.UUID,
        pickup_ids: list[uuid.UUID],
        origin_latitude: Decimal | None = None,
        origin_longitude: Decimal | None = None,
        stop_coordinates: dict[uuid.UUID, Point] | None = None,
        destination_latitude: Decimal | None = None,
        destination_longitude: Decimal | None = None,
        start_at: datetime | None = None,
        change_reason: str | None = None,
        force_recalculate: bool = False,
    ) -> Route:
        if not pickup_ids or len(pickup_ids) > self.settings.route_max_stops:
            raise RouteValidationError(f"Select between 1 and {self.settings.route_max_stops} pickups.")
        if len(set(pickup_ids)) != len(pickup_ids):
            raise RouteValidationError("A pickup can only appear once in an optimized route.")

        vehicle = self.vehicles.get_by_id(vehicle_id)
        if vehicle is None:
            raise RouteValidationError("Vehicle not found.")
        if not self._can_manage(user, vehicle):
            raise RouteForbiddenError("You are not authorized to optimize this vehicle's route.")
        if vehicle.status == VehicleStatus.MAINTENANCE or not vehicle.is_active:
            raise RouteValidationError("The selected vehicle is not available for route planning.")

        # Never supersede a live journey or recreate completed handovers.
        # Reoptimization of an active route is a separate, in-place operation.
        active_route = self.routes.get_active_for_vehicle(vehicle.id)
        if active_route is not None:
            raise RouteValidationError(
                "Active route must use /routes/{route_id}/recalculate; completed handovers cannot be re-planned."
            )
        self._require_complete_assigned_pickup_set(vehicle.id, pickup_ids)
        pickups = self._get_pickups(vehicle, pickup_ids)
        total_weight = sum(self._weight(p) for p in pickups)
        if total_weight > float(vehicle.capacity_kg):
            raise RouteValidationError(
                f"Route load {total_weight:.2f} kg exceeds vehicle capacity {float(vehicle.capacity_kg):.2f} kg."
            )

        explicit = stop_coordinates or {}
        candidates = [
            StopCandidate(
                pickup=p,
                point=self._stop_point(p, explicit),
                weight_kg=self._weight(p),
                priority=p.priority,
                requested_at=p.requested_pickup_at,
                requested_end_at=p.requested_pickup_end_at,
            )
            for p in pickups
        ]
        origin = self._origin(
            vehicle.id,
            origin_latitude,
            origin_longitude,
            fallback=candidates[0].point if candidates else None,
        )
        destination = self._destination(pickups, destination_latitude, destination_longitude)

        # Issue 4: pickup IDs alone are not a valid cache key. Origin (including
        # live GPS), hospital/facility locations, load, priorities, windows,
        # departure time and routing configuration all affect the plan. The
        # request order matters too for deterministic tie breaking.
        now = datetime.now(timezone.utc)
        effective_start = max(self._utc(start_at or now), now)
        inputs = {
            "pickup_ids": [str(p.id) for p in pickups],
            "pickup_facts": [{
                "id": str(candidate.pickup.id),
                "status": candidate.pickup.status.value,
                "assigned_collector_id": str(candidate.pickup.assigned_collector_id),
                "priority": candidate.priority.value,
                "weight_kg": str(Decimal(str(candidate.weight_kg))),
                "requested_at": self._utc(candidate.requested_at).isoformat() if candidate.requested_at else None,
                "requested_end_at": self._utc(candidate.requested_end_at).isoformat() if candidate.requested_end_at else None,
                "stop": [round(candidate.point.latitude, 6), round(candidate.point.longitude, 6)],
                "confirmed_facility_id": (
                    str(facility.id) if (facility := self._facility_for_pickup(candidate.pickup)) else None
                ),
            } for candidate in candidates],
            "origin": [round(origin.latitude, 6), round(origin.longitude, 6)],
            "destination": [round(destination.latitude, 6), round(destination.longitude, 6)],
            "planned_start_at": effective_start.isoformat(),
            "vehicle_capacity_kg": str(vehicle.capacity_kg),
            "vehicle_status": vehicle.status.value,
            "vehicle_assigned_collector_id": str(vehicle.assigned_collector_id),
            "routing": {
                "provider": self.settings.routing_provider.lower(),
                "base_url": self.settings.routing_base_url,
                "average_speed_kmh": self.settings.routing_average_speed_kmh,
                "max_duration_minutes": self.settings.route_max_duration_minutes,
            },
        }
        signature = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

        # A caller explicitly requesting recalculation must *never* hit the
        # idempotency shortcut. With an omitted or elapsed departure time,
        # real-world ETAs advance; return a fresh plan rather than a stale one.
        cache_allowed = (not force_recalculate and start_at is not None
                         and self._utc(start_at) > now)
        if cache_allowed:
            requested_pickups = set(pickup_ids)
            points_by_pickup = {c.pickup.id: c.point for c in candidates}
            for existing in self.routes.list_for_vehicle(vehicle.id):
                if existing.status not in {RouteStatus.DRAFT, RouteStatus.READY} or not existing.is_optimized:
                    continue
                details = existing.optimization_details or {}
                if details.get("input_fingerprint") != signature:
                    # Old routes without a fingerprint are intentionally NOT
                    # reused. The current request must produce a verified plan.
                    continue
                existing_stops = self.routes.list_stops(existing.id)
                if len(existing_stops) != len(pickups) or {s.pickup_id for s in existing_stops} != requested_pickups:
                    continue
                if any(
                    round(float(s.latitude), 6) != round(points_by_pickup[s.pickup_id].latitude, 6)
                    or round(float(s.longitude), 6) != round(points_by_pickup[s.pickup_id].longitude, 6)
                    for s in existing_stops
                ):
                    continue
                # A matching fingerprint is not a waiver of Issue 2 deadlines.
                self._validate_existing_windows(existing_stops, pickups, route=existing)
                self._validate_dispatch_destination(pickups)
                return existing

        provider, fallback = self._providers()
        try:
            ordered = self._optimize_order(candidates, origin, destination, provider)
            points = [origin] + [c.point for c in ordered] + [destination]
            distance, duration, geometry = provider.route(points)
            used_provider = provider.name
        except Exception:
            if self.settings.routing_provider.lower() == "osrm":
                raise RouteValidationError("Configured routing provider is unavailable.")
            ordered = self._optimize_order(candidates, origin, destination, fallback)
            points = [origin] + [c.point for c in ordered] + [destination]
            distance, duration, geometry = fallback.route(points)
            used_provider = fallback.name

        if duration > self.settings.route_max_duration_minutes:
            raise RouteValidationError(
                f"Optimized route duration {duration} minutes exceeds configured maximum "
                f"of {self.settings.route_max_duration_minutes} minutes."
            )

        old = self.routes.get_active_for_vehicle(vehicle.id)
        # Validate all hospital time windows BEFORE superseding existing routes.
        # A failed optimization must not invalidate a dispatchable draft.
        # The departure has already been normalized above for both the
        # fingerprint and ETA calculation. Keep the two identical.
        segment_provider = provider if used_provider == provider.name else fallback
        arrivals, last_arrival = self._schedule_arrivals(ordered, origin, effective_start, segment_provider)
        final_point = ordered[-1].point if ordered else origin
        _, final_minutes, _ = segment_provider.route([final_point, destination])
        completed_eta = last_arrival + timedelta(minutes=final_minutes)
        total_duration_minutes = math.ceil((completed_eta - effective_start).total_seconds() / 60)
        if total_duration_minutes > self.settings.route_max_duration_minutes:
            raise RouteValidationError(
                f"Optimized route duration {total_duration_minutes} minutes exceeds configured maximum "
                f"of {self.settings.route_max_duration_minutes} minutes."
            )

        for prior in self.routes.list_for_vehicle(vehicle.id):
            if prior.status in {RouteStatus.DRAFT, RouteStatus.READY}:
                prior.status = RouteStatus.CANCELLED
                prior.change_reason = "Superseded by a newly optimized route."
        version = self.routes.next_version_for_vehicle(vehicle.id)

        baseline = None
        if old is not None:
            baseline = {
                "distance_km": float(old.total_distance_km) if old.total_distance_km is not None else None,
                "duration_minutes": old.estimated_duration_minutes,
            }

        details = {
            "input_fingerprint": signature,
            "input_fingerprint_version": 1,
            "algorithm": ("priority_earliest_deadline" if any(c.requested_end_at for c in candidates)
                          else "priority_seeded_nearest_neighbor_2opt"),
            "planned_start_at": effective_start.isoformat(),
            "stop_count": len(ordered),
            "total_load_kg": round(total_weight, 2),
            "constraints": {
                "vehicle_capacity": True,
                "priority": True,
                "requested_pickup_time": any(c.requested_at is not None for c in candidates),
                "requested_pickup_end_time": any(c.requested_end_at is not None for c in candidates),
                "facility_destination": True,
                "max_route_duration": True,
            },
            "optimization_provider": used_provider,
            "baseline_route": baseline,
            "distance_reduction_km": (
                round(baseline["distance_km"] - distance, 2)
                if baseline and baseline["distance_km"] is not None else None
            ),
            "duration_reduction_minutes": (
                baseline["duration_minutes"] - duration
                if baseline and baseline["duration_minutes"] is not None else None
            ),
        }

        if old is not None:
            old.status = RouteStatus.CANCELLED
            old.change_reason = change_reason or "Superseded by optimized route."

        active_tracking = self.tracking.get_active_for_vehicle(vehicle.id)
        route = Route(
            vehicle_id=vehicle.id,
            tracking_session_id=active_tracking.id if active_tracking else None,
            version=version,
            status=RouteStatus.DRAFT,
            destination_state=RouteDestinationState.COLLECTION.value,
            is_optimized=True,
            total_distance_km=Decimal(str(round(distance, 2))),
            estimated_duration_minutes=total_duration_minutes,
            origin_latitude=Decimal(str(origin.latitude)),
            origin_longitude=Decimal(str(origin.longitude)),
            destination_latitude=Decimal(str(destination.latitude)),
            destination_longitude=Decimal(str(destination.longitude)),
            change_reason=change_reason,
            routing_provider=used_provider,
            geometry=geometry,
            optimization_details=details,
        )

        stops = [
            RouteStop(
                route_id=route.id,
                pickup_id=candidate.pickup.id,
                sequence=sequence,
                latitude=Decimal(str(candidate.point.latitude)),
                longitude=Decimal(str(candidate.point.longitude)),
                status=RouteStopStatus.PENDING,
                estimated_arrival_at=arrival,
            )
            for sequence, (candidate, arrival) in enumerate(zip(ordered, arrivals), start=1)
        ]
        # The full duration includes waiting for future hospital windows.
        route.optimization_details["duration_reduction_minutes"] = (
            old.estimated_duration_minutes - total_duration_minutes
            if old is not None and old.estimated_duration_minutes is not None else None
        )

        self.db.add(route)
        self.db.flush()
        if active_tracking is not None:
            active_tracking.current_route_id = route.id
        for stop in stops:
            stop.route_id = route.id
            self.db.add(stop)
        self.db.commit()
        self.db.refresh(route)
        return route

    def recalculate_active(self, *, user: User, route_id: uuid.UUID, reason: str) -> Route:
        """Reorder *only* unstarted hospital stops, preserving every committed stop.

        The route keeps its ID and tracking session. A vehicle row lock serializes
        re-plans with other route-management commands on PostgreSQL.
        """
        route = self.db.scalar(select(Route).where(Route.id == route_id).with_for_update(of=Route))
        if route is None or route.status != RouteStatus.ACTIVE:
            raise RouteValidationError("Only an active route can be recalculated in place.")
        vehicle = self.db.scalar(select(Vehicle).where(Vehicle.id == route.vehicle_id).with_for_update(of=Vehicle))
        if vehicle is None or not self._can_manage(user, vehicle):
            raise RouteForbiddenError("You are not authorized to recalculate this vehicle's route.")
        if not reason or len(reason.strip()) < 8:
            raise RouteValidationError("An operational reason of at least eight characters is required.")
        all_stops = sorted(self.routes.list_stops(route.id), key=lambda s: s.sequence)
        locked = [s for s in all_stops if s.status != RouteStopStatus.PENDING]
        # Completed, arrived, en-route and skipped/cancelled stops are immutable.
        pending = [s for s in all_stops if s.status == RouteStopStatus.PENDING]
        if not pending:
            return route
        # A single pending stop still needs a fresh arrival/deadline check;
        # otherwise recalculation could report success for an expired window.
        if route.destination_state != RouteDestinationState.COLLECTION.value:
            raise RouteValidationError("Facility-bound journeys cannot reorder hospital stops.")
        pickups = self._get_pickups(vehicle, [s.pickup_id for s in pending])
        explicit = {s.pickup_id: Point(float(s.latitude), float(s.longitude)) for s in pending}
        candidates = [StopCandidate(p, explicit[p.id], self._weight(p), p.priority,
                                    p.requested_pickup_at, p.requested_pickup_end_at)
                      for p in pickups]
        latest = self.tracking.get_latest_location(vehicle.id)
        origin = (Point(float(latest.latitude), float(latest.longitude)) if latest is not None
                  else Point(float(locked[-1].latitude), float(locked[-1].longitude)) if locked
                  else Point(float(route.origin_latitude), float(route.origin_longitude)))
        destination = self._destination(pickups, route.destination_latitude, route.destination_longitude)
        provider, fallback = self._providers()
        try:
            ordered = self._optimize_order(candidates, origin, destination, provider)
            distance, duration, geometry = provider.route([origin] + [s.point for s in ordered] + [destination])
            used_provider = provider
        except Exception:
            if self.settings.routing_provider.lower() == "osrm":
                raise RouteValidationError("Configured routing provider is unavailable.")
            ordered = self._optimize_order(candidates, origin, destination, fallback)
            distance, duration, geometry = fallback.route([origin] + [s.point for s in ordered] + [destination])
            used_provider = fallback
        # Compute the entire remaining schedule before modifying stop sequences.
        # Previously a reoptimization could write new ETAs after hard deadlines.
        replan_start = datetime.now(timezone.utc)
        arrivals, last_arrival = self._schedule_arrivals(ordered, origin, replan_start, used_provider)
        final_point = ordered[-1].point if ordered else origin
        _, facility_minutes, _ = used_provider.route([final_point, destination])
        remaining_duration = math.ceil((last_arrival + timedelta(minutes=facility_minutes) - replan_start).total_seconds() / 60)
        if remaining_duration > self.settings.route_max_duration_minutes:
            raise RouteValidationError("Reoptimized remaining journey exceeds max route duration.")
        old_order = [str(s.pickup_id) for s in all_stops]
        pending_map = {s.pickup_id: s for s in pending}
        # Temporary sequence IDs prevent unique-key collisions during reordering.
        for i, stop in enumerate(pending, start=1):
            stop.sequence = len(all_stops) + i
        self.db.flush()
        start_sequence = max((s.sequence for s in locked), default=0) + 1
        for i, (candidate, arrival) in enumerate(zip(ordered, arrivals)):
            stop = pending_map[candidate.pickup.id]
            stop.sequence = start_sequence + i
            stop.estimated_arrival_at = arrival
        old_metadata = dict(route.optimization_details or {})
        history = list(old_metadata.get("reoptimizations", []))
        history.append({"at": datetime.now(timezone.utc).isoformat(), "reason": reason.strip()[:500],
                        "by": str(user.id), "old_order": old_order,
                        "new_order": [str(s.pickup_id) for s in locked] + [str(c.pickup.id) for c in ordered],
                        "remaining_distance_km": round(distance, 2), "remaining_eta_min": remaining_duration})
        old_metadata["reoptimizations"] = history
        old_metadata["remaining_distance_km"] = round(distance, 2)
        old_metadata["remaining_duration_minutes"] = remaining_duration
        route.optimization_details = old_metadata
        route.change_reason = reason.strip()[:500]
        route.geometry = geometry
        route.routing_provider = used_provider.name
        route.destination_latitude = Decimal(str(round(destination.latitude, 6)))
        route.destination_longitude = Decimal(str(round(destination.longitude, 6)))
        self.db.commit()
        self.db.refresh(route)
        return route

    def confirm(self, *, user: User, route_id: uuid.UUID) -> Route:
        route = self.routes.get_by_id(route_id)
        if route is None:
            raise RouteValidationError("Route not found.")
        vehicle = self.vehicles.get_by_id(route.vehicle_id)
        if vehicle is None or not self._can_manage(user, vehicle):
            raise RouteForbiddenError("You are not authorized to confirm this route.")
        if route.status == RouteStatus.READY:
            # Confirm is idempotent, but an already-ready route may have missed
            # a deadline since its first approval. Do not silently reconfirm it.
            ready_stops = self.routes.list_stops(route.id)
            if ready_stops:
                ready_pickups = self._get_pickups(vehicle, [s.pickup_id for s in ready_stops])
                self._validate_existing_windows(ready_stops, ready_pickups, route=route)
                self._require_current_route_destination(route, ready_pickups)
                self._validate_dispatch_destination(ready_pickups)
            return route
        if route.status == RouteStatus.ACTIVE:
            raise RouteValidationError("Cannot confirm a route that has already started.")
        if route.status != RouteStatus.DRAFT:
            raise RouteValidationError("Only a draft route can be confirmed.")
        if vehicle.status != VehicleStatus.RESERVED or not vehicle.is_active:
            raise RouteValidationError("Vehicle reservation changed. Reoptimize this route.")
        stops = self.routes.list_stops(route.id)
        if not stops:
            raise RouteValidationError("Cannot confirm an empty route.")
        pickups = self._get_pickups(vehicle, [stop.pickup_id for stop in stops])
        live_ids = set(self.db.scalars(select(PickupRequest.id).where(
            PickupRequest.assigned_vehicle_id == vehicle.id,
            PickupRequest.status == PickupStatus.ASSIGNED)).all())
        if live_ids != {stop.pickup_id for stop in stops}:
            raise RouteValidationError("Vehicle pickup set changed. Reoptimize this route.")
        if any(pickup.status != PickupStatus.ASSIGNED for pickup in pickups):
            raise RouteValidationError("Pickup assignment changed. Reoptimize this route.")
        self._validate_existing_windows(stops, pickups, route=route)
        self._require_current_route_destination(route, pickups)
        self._validate_dispatch_destination(pickups)
        route.status = RouteStatus.READY
        self.db.commit()
        self.db.refresh(route)
        return route

    def start(self, *, user: User, route_id: uuid.UUID) -> Route:
        # Serialize route activation at vehicle scope before checking other
        # active routes. A partial unique index is the final database guard.
        initial = self.routes.get_by_id(route_id)
        if initial is None:
            raise RouteValidationError("Route not found.")
        self.db.scalar(select(Vehicle).where(Vehicle.id == initial.vehicle_id).with_for_update(of=Vehicle))
        route = self.routes.get_by_id(route_id)
        if route is None:
            raise RouteValidationError("Route not found.")
        vehicle = self.vehicles.get_by_id(route.vehicle_id)
        if vehicle is None or not self._can_manage(user, vehicle):
            raise RouteForbiddenError("You are not authorized to start this route.")
        if route.status == RouteStatus.ACTIVE:
            return route
        if route.status != RouteStatus.READY:
            raise RouteValidationError("Confirm the route before starting it.")

        active = self.routes.get_active_for_vehicle(vehicle.id)
        if active is not None and active.id != route.id:
            raise RouteValidationError("This vehicle already has an active route.")
        # A route approved yesterday is not authority to collect a pickup
        # cancelled/reassigned since then. Re-check its live DB state at start.
        planned_stops = self.routes.list_stops(route.id)
        if not planned_stops or vehicle.status != VehicleStatus.RESERVED:
            raise RouteValidationError("Vehicle must be reserved for an eligible planned route.")
        planned_pickups = self._get_pickups(vehicle, [s.pickup_id for s in planned_stops])
        # All currently reserved/assigned pickups must be represented. Otherwise
        # activating the route would silently strand a pickup on an ON_ROUTE vehicle.
        assigned_ids = set(self.db.scalars(select(PickupRequest.id).where(
            PickupRequest.assigned_vehicle_id == vehicle.id,
            PickupRequest.status == PickupStatus.ASSIGNED)).all())
        if assigned_ids != {stop.pickup_id for stop in planned_stops}:
            raise RouteValidationError("Route stops no longer match the vehicle's assigned pickups. Reoptimize the route.")
        if any(p.status != PickupStatus.ASSIGNED for p in planned_pickups):
            raise RouteValidationError("Collected or cancelled pickups cannot start a new route.")
        self._validate_existing_windows(planned_stops, planned_pickups, route=route)
        if sum(self._weight(p) for p in planned_pickups) > float(vehicle.capacity_kg):
            raise RouteValidationError("Planned route now exceeds vehicle capacity.")
        self._require_current_route_destination(route, planned_pickups)
        self._validate_dispatch_destination(planned_pickups)

        session = self.tracking.get_active_for_vehicle(vehicle.id)
        if session is not None and session.current_route_id not in (None, route.id):
            raise RouteValidationError("This vehicle already has an active tracking session.")
        if session is None:
            session = TrackingSession(
                vehicle_id=vehicle.id,
                current_route_id=route.id,
                status=TrackingSessionStatus.ACTIVE,
                started_at=datetime.now(timezone.utc),
            )
            self.db.add(session)
            self.db.flush()
        else:
            session.current_route_id = route.id
            session.status = TrackingSessionStatus.ACTIVE
            session.started_at = session.started_at or datetime.now(timezone.utc)
            session.ended_at = None

        route.status = RouteStatus.ACTIVE
        route.destination_state = RouteDestinationState.COLLECTION.value
        route.destination_arrived_at = None
        route.destination_received_at = None
        route.completed_at = None
        route.tracking_session_id = session.id
        vehicle.status = VehicleStatus.ON_ROUTE
        stops = self.routes.list_stops(route.id)
        first = next((stop for stop in stops if stop.status == RouteStopStatus.PENDING), None)
        if first is not None:
            first.status = RouteStopStatus.EN_ROUTE
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            if 'uq_tracking_vehicle_open_session' in str(exc.orig).lower() or 'tracking_sessions.vehicle_id' in str(exc.orig).lower():
                raise RouteValidationError('This vehicle already has an active tracking session.') from exc
            raise
        self.db.refresh(route)
        return route

    def complete_stop(self, *, user: User, route_id: uuid.UUID, stop_id: uuid.UUID) -> Route:
        route = self.routes.get_by_id(route_id)
        if route is None:
            raise RouteValidationError("Route not found.")
        vehicle = self.vehicles.get_by_id(route.vehicle_id)
        if vehicle is None or not self._can_manage(user, vehicle):
            raise RouteForbiddenError("You are not authorized to update this route.")
        if route.status != RouteStatus.ACTIVE:
            raise RouteValidationError("Only an active route can complete a stop.")
        stop = self.db.get(RouteStop, stop_id)
        if stop is None or stop.route_id != route.id:
            raise RouteValidationError("Route stop not found.")
        pickup = self.db.get(PickupRequest, stop.pickup_id)
        if stop.status != RouteStopStatus.COLLECTED or pickup is None or pickup.status not in {
            PickupStatus.COLLECTED, PickupStatus.IN_TRANSIT, PickupStatus.COMPLETED,
        }:
            raise RouteValidationError("Verified hospital handover must be completed via pickup proof flow first.")

        stops = self.routes.list_stops(route.id)
        next_stop = next(
            (candidate for candidate in stops if candidate.status == RouteStopStatus.PENDING),
            None,
        )
        if next_stop is not None:
            next_stop.status = RouteStopStatus.EN_ROUTE
        elif all(candidate.status in {RouteStopStatus.COLLECTED, RouteStopStatus.SKIPPED, RouteStopStatus.CANCELLED} for candidate in stops):
            # Collection is complete, but transport is NOT complete. The
            # Treatment Facility is the authoritative final destination.
            route.destination_state = RouteDestinationState.EN_ROUTE_TO_DESTINATION.value
        self.db.commit()
        self.db.refresh(route)
        return route
