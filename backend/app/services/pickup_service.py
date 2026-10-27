import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pickup_request import PickupRequest
from app.models.vehicle import Vehicle
from app.models.collection_proof import CollectionProof
from app.models.incident import Incident
from app.models.audit_log import AuditLog
from app.models.waste_enums import IncidentType
from app.services.collection_weight_guard import check_collection_load, CollectionWeightError
from app.models.notification import Notification
from app.models.business import Organization, OrganizationMember
from app.models.user import User
from app.models.roles import UserRole
from app.services.business_finance import operator_accepts_new_work
from app.services.organization_eligibility import can_profile_action
from app.models.route import Route, RouteStatus, RouteStop, RouteStopStatus, RouteDestinationState
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.waste_enums import PickupStatus, VehicleStatus, WasteEventType, WasteStatus
from app.repositories.hospital_repository import HospitalRepository
from app.repositories.matching_repository import MatchingRepository
from app.repositories.pickup_repository import PickupRequestRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.waste_record_repository import WasteRecordRepository
from app.rules.pickup_scheduling_rules import schedule_pickup
from app.schemas.pickup import PickupRequestCreate
from app.services.notification_service import NotificationService
from app.services.waste_event_service import WasteEventService
from app.services.quantity_service import quantity_to_kg
from app.realtime.tracking_manager import route_topic, tracking_manager, vehicle_topic
from app.services.waste_service import (
    HospitalProfileRequiredError,
    WasteRecordNotFoundError,
    WasteService,
)


class DestinationNotConfirmedError(Exception):
    def __init__(self, waste_code: str): self.waste_code = waste_code


class WasteRecordNotEligibleError(Exception):
    """Raised when a waste record isn't risk-assessed yet, or is already
    attached to another active pickup."""

    def __init__(self, waste_code: str):
        self.waste_code = waste_code


class PickupNotFoundError(Exception):
    pass


class PickupNotCancellableError(Exception):
    pass


class PickupNotAssignableError(Exception):
    pass


class NotAssignedCollectorError(Exception):
    pass


class PickupNotCollectableError(Exception):
    pass


class PickupNotInTransitableError(Exception):
    pass


class PickupWeightValidationError(PickupNotCollectableError):
    """Actionable handover error: failed route load or discrepancy check."""
    pass


class PickupService:
    def __init__(self, db: Session):
        self.db = db
        self.waste_service = WasteService(db)
        self.pickups = PickupRequestRepository(db)
        self.vehicles = VehicleRepository(db)
        self.records = WasteRecordRepository(db)
        self.hospitals = HospitalRepository(db)
        self.matches = MatchingRepository(db)
        self.events = WasteEventService(db)
        self.notifications = NotificationService(db)

    def _require_hospital_profile(self, user_id: uuid.UUID):
        profile = self.hospitals.get_by_user_id(user_id)
        if profile is None:
            raise HospitalProfileRequiredError()
        return profile

    def _vehicle_has_eligible_driver(self, vehicle: Vehicle) -> bool:
        """Do not reserve a vehicle with a disabled, wrong-role or removed driver.

        For company vehicles the driver must have an ACTIVE organization
        membership that is authorized to operate the vehicle. Legacy
        unscoped demo vehicles are allowed only by the existing environment
        gate in _run_auto_assignment.
        """
        driver_id = vehicle.assigned_collector_id
        if driver_id is None:
            return False
        driver_exists = self.db.scalar(select(User.id).where(
            User.id == driver_id,
            User.is_active.is_(True),
            User.role == UserRole.COLLECTOR,
        ).limit(1))
        if driver_exists is None:
            return False
        if vehicle.organization_id is None:
            return True
        membership = self.db.scalar(select(OrganizationMember.id).where(
            OrganizationMember.organization_id == vehicle.organization_id,
            OrganizationMember.user_id == driver_id,
            OrganizationMember.active.is_(True),
            OrganizationMember.member_role.in_({'owner', 'manager', 'dispatcher', 'driver'}),
        ).limit(1))
        return membership is not None

    def _run_auto_assignment(self, pickup: PickupRequest, *, required_capacity: Decimal) -> None:
        # Lock candidate vehicles before assigning, so concurrent requests cannot
        # book the same capacity. A reserved vehicle can share compatible jobs
        # for the same destination without being marked on the road.
        vehicles = list(self.db.scalars(
            select(Vehicle).where(
                Vehicle.is_active.is_(True),
                Vehicle.status.in_([VehicleStatus.AVAILABLE, VehicleStatus.RESERVED]),
            ).order_by(Vehicle.capacity_kg, Vehicle.id).with_for_update(skip_locked=True, of=Vehicle)
        ).all())
        destination_ids = {
            self.matches.get_confirmed_for_record(item.waste_record_id).confirmed_facility_id
            for item in pickup.items
        }
        # A single trip must not mix destinations. Keep incompatible jobs in
        # the dispatch queue until they are split into destination-safe routes.
        candidates = []
        if len(destination_ids) != 1:
            vehicles = []
        for vehicle in vehicles:
            if not self._vehicle_has_eligible_driver(vehicle):
                # Keep the pickup REQUESTED and leave the vehicle untouched;
                # dispatch can be retried when a valid driver is assigned.
                continue
            # Legacy unscoped vehicles are not eligible for commercial dispatch.
            if vehicle.organization_id is not None:
                if not operator_accepts_new_work(self.db, vehicle.organization_id, datetime.now(timezone.utc).date()):
                    continue
            else:
                # During migration, unlinked vehicles may be operated only in
                # explicitly local development mode (not paid jobs).
                from app.core.config import get_settings
                if get_settings().environment.lower() not in {'development','test'}:
                    continue
            active = list(self.db.scalars(select(PickupRequest).where(
                PickupRequest.assigned_vehicle_id == vehicle.id,
                PickupRequest.status == PickupStatus.ASSIGNED,
            )).all())
            booked = Decimal('0')
            compatible = True
            for other in active:
                for item in other.items:
                    booked += quantity_to_kg(item.waste_record.quantity, item.waste_record.unit) or Decimal('0')
                    match = self.matches.get_confirmed_for_record(item.waste_record_id)
                    if not match or match.confirmed_facility_id not in destination_ids:
                        compatible = False
            if compatible and booked + required_capacity <= Decimal(str(vehicle.capacity_kg)):
                candidates.append(vehicle)
        result = schedule_pickup(
            priority=pickup.priority, required_capacity=required_capacity,
            candidate_vehicles=candidates, requested_at=pickup.requested_pickup_at,
            requested_end_at=pickup.requested_pickup_end_at,
        )
        pickup.scheduled_at = result.scheduled_at

        if result.vehicle is not None:
            result.vehicle.status = VehicleStatus.RESERVED
            self.db.flush()

            pickup.assigned_vehicle_id = result.vehicle.id
            pickup.assigned_collector_id = result.vehicle.assigned_collector_id
            pickup.status = PickupStatus.ASSIGNED

            for item in pickup.items:
                self.records.set_status(record=item.waste_record, status=WasteStatus.PICKUP_ASSIGNED, commit=False)
                self.events.record(
                    waste_record_id=item.waste_record_id,
                    event_type=WasteEventType.PICKUP_ASSIGNED,
                    status_snapshot=WasteStatus.PICKUP_ASSIGNED,
                    actor_user_id=None,
                    quantity=item.waste_record.quantity,
                    notes=f"Assigned to vehicle {result.vehicle.vehicle_code}.",
                    metadata={"vehicle_code": result.vehicle.vehicle_code, "priority": pickup.priority.value},
                    commit=False,
                )

            self.db.add(Notification(
                user_id=result.vehicle.assigned_collector_id,
                title=f"New pickup assigned: {result.vehicle.vehicle_code}",
                body=f"{len(pickup.items)} batch(es) scheduled.",
            ))
        else:
            for item in pickup.items:
                self.records.set_status(record=item.waste_record, status=WasteStatus.PICKUP_REQUESTED, commit=False)

        self.pickups.save(pickup, commit=False)

    def create_pickup(self, *, user_id: uuid.UUID, data: PickupRequestCreate) -> PickupRequest:
        profile = self._require_hospital_profile(user_id)
        if not can_profile_action(self.db, profile, user_id, "HOSPITAL", "pickup_write"):
            raise PermissionError("Organization member cannot create pickups")

        # Serialize concurrent pickup submissions for the same waste batches.
        # PostgreSQL row locks prevent duplicate active jobs for one batch.
        from app.models.waste_record import WasteRecord
        self.db.scalars(select(WasteRecord).where(
            WasteRecord.id.in_(data.waste_record_ids)
        ).order_by(WasteRecord.id).with_for_update(of=WasteRecord)).all()
        waste_records = []
        for record_id in data.waste_record_ids:
            try:
                record = self.waste_service.get_record(user_id=user_id, record_id=record_id)
            except WasteRecordNotFoundError:
                raise
            if record.status != WasteStatus.RISK_ASSESSED:
                raise WasteRecordNotEligibleError(record.waste_code)
            match = self.matches.get_confirmed_for_record(record.id)
            if match is None or match.confirmed_facility_id is None:
                raise DestinationNotConfirmedError(record.waste_code)
            if self.pickups.get_active_pickup_for_waste_record(record.id) is not None:
                raise WasteRecordNotEligibleError(record.waste_code)
            if quantity_to_kg(record.quantity, record.unit) is None:
                raise WasteRecordNotEligibleError(record.waste_code)
            waste_records.append(record)

        pickup = PickupRequest(
            hospital_id=profile.id,
            requested_by=user_id,
            priority=data.priority,
            status=PickupStatus.REQUESTED,
            notes=data.notes,
            requested_pickup_at=data.requested_pickup_at,
            requested_pickup_end_at=data.requested_pickup_end_at,
        )
        self.db.add(pickup)
        self.db.flush()

        for record in waste_records:
            self.pickups.add_item(pickup.id, record.id)
        self.db.flush()

        for record in waste_records:
            self.events.record(
                waste_record_id=record.id,
                event_type=WasteEventType.PICKUP_REQUESTED,
                status_snapshot=WasteStatus.PICKUP_REQUESTED,
                actor_user_id=user_id,
                quantity=record.quantity,
                notes=f"Pickup requested ({data.priority.value} priority).",
                metadata={"priority": data.priority.value},
                commit=False,
            )

        pickup = self.pickups.get_by_id(pickup.id)
        quantities_kg = [quantity_to_kg(r.quantity, r.unit) for r in waste_records]
        total_quantity = sum((q for q in quantities_kg if q is not None), Decimal("0"))
        self._run_auto_assignment(pickup, required_capacity=total_quantity)
        self.db.commit()
        return self.pickups.get_by_id(pickup.id)

    def get_pickup(self, *, user_id: uuid.UUID, pickup_id: uuid.UUID, action: str = 'waste_read') -> PickupRequest:
        profile = self._require_hospital_profile(user_id)
        if not can_profile_action(self.db, profile, user_id, 'HOSPITAL', action):
            raise PermissionError('Organization cannot perform this pickup operation')
        pickup = self.pickups.get_by_id_for_hospital(pickup_id=pickup_id, hospital_id=profile.id)
        if pickup is None:
            raise PickupNotFoundError()
        return pickup

    def search_pickups(self, *, user_id: uuid.UUID, page: int, page_size: int, status=None):
        profile = self._require_hospital_profile(user_id)
        return self.pickups.search_for_hospital(
            hospital_id=profile.id, page=page, page_size=page_size, status=status
        )

    def cancel_pickup(
        self, *, user_id: uuid.UUID, pickup_id: uuid.UUID, reason: str | None
    ) -> PickupRequest:
        pickup = self.get_pickup(user_id=user_id, pickup_id=pickup_id, action="pickup_write")
        if pickup.status not in (PickupStatus.REQUESTED, PickupStatus.ASSIGNED):
            raise PickupNotCancellableError()

        now = datetime.now(timezone.utc)
        vehicle = None
        active_route = None
        route_stop = None
        if pickup.assigned_vehicle_id is not None:
            # Use the same stop -> vehicle lock ordering as the collection
            # handover flow. A cancellation must not race a verified handover.
            route_stop = self.db.scalar(select(RouteStop).join(Route).where(
                RouteStop.pickup_id == pickup.id,
                Route.vehicle_id == pickup.assigned_vehicle_id,
                Route.status == RouteStatus.ACTIVE,
            ).limit(1).with_for_update(of=RouteStop))
            vehicle = self.db.scalar(select(Vehicle).where(
                Vehicle.id == pickup.assigned_vehicle_id).with_for_update(of=Vehicle))
            if route_stop is not None:
                active_route = self.db.get(Route, route_stop.route_id)
                if route_stop.status not in {
                    RouteStopStatus.PENDING, RouteStopStatus.EN_ROUTE, RouteStopStatus.ARRIVED,
                }:
                    raise PickupNotCancellableError()
        # Refresh after waiting for concurrent route/vehicle operations.
        pickup = self.db.scalar(select(PickupRequest).where(
            PickupRequest.id == pickup.id).with_for_update(of=PickupRequest).execution_options(populate_existing=True))
        if pickup is None or pickup.status not in (PickupStatus.REQUESTED, PickupStatus.ASSIGNED):
            raise PickupNotCancellableError()

        if vehicle is not None:
            ready_routes = list(self.db.scalars(select(Route).join(RouteStop).where(
                Route.vehicle_id == vehicle.id,
                Route.status.in_([RouteStatus.DRAFT, RouteStatus.READY]),
                RouteStop.pickup_id == pickup.id,
            ).with_for_update(of=Route)).all())
            for old_route in ready_routes:
                old_route.status = RouteStatus.CANCELLED
                old_route.change_reason = f"Planned pickup {pickup.id} cancelled; re-plan required."

        # Physical route progress is reconciled BEFORE lifting the facility's
        # reservation and publishing the cancellation event. Everything commits
        # together, or the entire state transition rolls back.
        if active_route is not None and route_stop is not None and vehicle is not None:
            from app.services.active_route_cancellation import reconcile_cancelled_stop
            from app.models.audit_log import AuditLog
            outcome = reconcile_cancelled_stop(
                self.db, route=active_route, cancelled_stop=route_stop,
                vehicle=vehicle, pickup=pickup, timestamp=now,
            )
            self.db.add(AuditLog(
                actor_user_id=user_id, action="pickup.cancel.active_route",
                entity_type="pickup", entity_id=str(pickup.id),
                details={"route_id": str(active_route.id), "stop_id": str(route_stop.id),
                         "outcome": outcome, "reason": (reason or "")[:500]},
            ))
        elif vehicle is not None:
            still_active = self.db.scalar(select(Route.id).where(
                Route.vehicle_id == vehicle.id, Route.status == RouteStatus.ACTIVE
            ).limit(1))
            another_assigned = self.db.scalar(select(PickupRequest.id).where(
                PickupRequest.assigned_vehicle_id == vehicle.id,
                PickupRequest.id != pickup.id,
                PickupRequest.status == PickupStatus.ASSIGNED,
            ).limit(1))
            if still_active is None:
                vehicle.status = VehicleStatus.RESERVED if another_assigned is not None else VehicleStatus.AVAILABLE

        for item in pickup.items:
            match = self.matches.get_confirmed_for_record(item.waste_record_id)
            if match and match.confirmed_facility_id:
                facility = self.db.get(TreatmentFacilityProfile, match.confirmed_facility_id)
                if facility is not None:
                    reserved_kg = quantity_to_kg(item.waste_record.quantity, item.waste_record.unit) or Decimal("0")
                    facility.current_utilization_kg = max(Decimal("0"), Decimal(str(facility.current_utilization_kg)) - reserved_kg)
            self.records.set_status(record=item.waste_record, status=WasteStatus.RISK_ASSESSED, commit=False)
            self.events.record(
                waste_record_id=item.waste_record_id,
                event_type=WasteEventType.PICKUP_CANCELLED,
                status_snapshot=WasteStatus.RISK_ASSESSED,
                actor_user_id=user_id,
                quantity=item.waste_record.quantity,
                notes="Pickup cancelled." + (f" Reason: {reason}" if reason else ""),
                metadata={"reason": reason} if reason else {},
                commit=False,
            )

        pickup.status = PickupStatus.CANCELLED
        pickup.cancelled_at = now
        pickup.cancellation_reason = reason
        if pickup.assigned_collector_id is not None:
            self.db.add(Notification(
                user_id=pickup.assigned_collector_id,
                title="Hospital pickup cancelled",
                body=(f"Pickup {pickup.id} cancelled by the hospital. "
                      + ("Active route updated; refresh live directions. " if active_route else "Please update your planned route. ")
                      + ((reason or "")[:280])),
            ))
        self.pickups.save(pickup, commit=False)
        self.db.commit()
        self.db.refresh(pickup)
        return pickup

    def retry_assignment(self, *, user_id: uuid.UUID, pickup_id: uuid.UUID) -> PickupRequest:
        pickup = self.get_pickup(user_id=user_id, pickup_id=pickup_id, action="pickup_write")
        if pickup.status != PickupStatus.REQUESTED:
            raise PickupNotAssignableError()

        quantities_kg = [quantity_to_kg(item.waste_record.quantity, item.waste_record.unit) for item in pickup.items]
        if any(q is None for q in quantities_kg):
            raise PickupNotAssignableError()
        total_quantity = sum((q for q in quantities_kg if q is not None), Decimal("0"))
        self._run_auto_assignment(pickup, required_capacity=total_quantity)
        self.db.commit()
        return self.pickups.get_by_id(pickup.id)

    def list_assigned_for_collector(self, collector_id: uuid.UUID) -> list[PickupRequest]:
        return self.pickups.list_assigned_to_collector(collector_id)

    def _require_active_driver(self, collector_id: uuid.UUID, vehicle_id: uuid.UUID):
        from app.models.business import OrganizationMember
        vehicle = self.db.get(Vehicle, vehicle_id)
        if vehicle is None or vehicle.assigned_collector_id != collector_id:
            raise NotAssignedCollectorError()
        if vehicle.organization_id is None:
            return  # standalone legacy demo vehicles
        role = self.db.scalar(select(OrganizationMember.member_role).where(
            OrganizationMember.organization_id == vehicle.organization_id,
            OrganizationMember.user_id == collector_id,
            OrganizationMember.active.is_(True)).limit(1))
        if role not in {'owner', 'manager', 'dispatcher', 'driver'}:
            raise NotAssignedCollectorError()

    def mark_arrived(self, *, collector_id: uuid.UUID, pickup_id: uuid.UUID,
                     token: str, manual_reason: str | None = None,
                     demo_manual: bool = False) -> RouteStop:
        import hmac
        from app.models.audit_log import AuditLog
        from app.models.tracking import TrackingLocation, LocationSource
        from app.services.route_optimization_service import HaversineRoutingProvider, Point
        pickup = self.pickups.get_by_id(pickup_id)
        if pickup is None:
            raise PickupNotFoundError()
        if pickup.assigned_collector_id != collector_id:
            raise NotAssignedCollectorError()
        self._require_active_driver(collector_id, pickup.assigned_vehicle_id)
        if not hmac.compare_digest(token, pickup.handover_token):
            raise PickupNotCollectableError()
        stop = self.db.scalar(select(RouteStop).join(Route).where(
            RouteStop.pickup_id == pickup.id, Route.vehicle_id == pickup.assigned_vehicle_id,
            Route.status == RouteStatus.ACTIVE).limit(1).with_for_update(of=RouteStop))
        if stop is None or stop.status not in {RouteStopStatus.EN_ROUTE, RouteStopStatus.ARRIVED}:
            raise PickupNotCollectableError()
        if demo_manual:
            from app.core.config import get_settings
            settings = get_settings()
            if not settings.enable_demo_manual_workflow or settings.environment.lower() not in {"development", "test"}:
                raise PickupNotCollectableError()
            if stop.status != RouteStopStatus.EN_ROUTE:
                raise PickupNotCollectableError()
            stop.status = RouteStopStatus.ARRIVED
            stop.arrived_at = datetime.now(timezone.utc)
            self.db.add(AuditLog(actor_user_id=collector_id,
                action="pickup.arrival.demo_manual", entity_type="pickup", entity_id=str(pickup.id),
                details={"route_stop_id": str(stop.id), "driver_id": str(collector_id),
                         "hospital_qr_present": True, "simulated": True}))
            for item in pickup.items:
                self.events.record(waste_record_id=item.waste_record_id,
                    event_type=WasteEventType.PICKUP_ASSIGNED,
                    status_snapshot=WasteStatus.PICKUP_ASSIGNED,
                    actor_user_id=collector_id, quantity=item.waste_record.quantity,
                    notes="SIMULATED: Driver manually confirmed hospital arrival (not GPS evidence).",
                    metadata={"simulated": True, "manual_arrival": True,
                              "vehicle_id": str(pickup.assigned_vehicle_id)}, commit=False)
            self.db.commit()
            self.db.refresh(stop)
            return stop
        last = self.db.scalar(select(TrackingLocation).where(
            TrackingLocation.vehicle_id == pickup.assigned_vehicle_id,
        ).order_by(TrackingLocation.timestamp.desc()).limit(1))
        # Only sufficiently fresh, accurate, anomaly-free, non-simulator GPS may
        # establish automatic arrival; older/imported demo points cannot.
        last_time = last.timestamp if last is not None else None
        if last_time is not None and last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)  # SQLite test compatibility
        trusted_gps = bool(
            last is not None and last.source in {LocationSource.GPS_DEVICE, LocationSource.MOBILE_APP}
            and last.provenance_verified is True
            and last.tracking_session_id == self.db.get(Route, stop.route_id).tracking_session_id
            and last.anomaly_type is None
            and last.accuracy_m is not None and 0 <= float(last.accuracy_m) <= 100
            and 0 <= (datetime.now(timezone.utc) - last_time).total_seconds() <= 90
        )
        near = trusted_gps and HaversineRoutingProvider.distance(
            Point(float(last.latitude), float(last.longitude)),
            Point(float(stop.latitude), float(stop.longitude))) <= 0.2
        if not near:
            # When reliable GPS places the vehicle elsewhere, the driver cannot
            # bypass that evidence; an incident should be investigated instead.
            if trusted_gps or not manual_reason or len(manual_reason.strip()) < 12:
                raise PickupNotCollectableError()
            approval = self.db.scalar(select(AuditLog).where(
                AuditLog.action == "pickup.arrival.exception_approved",
                AuditLog.entity_type == "pickup",
                AuditLog.entity_id == str(pickup.id),
            ).order_by(AuditLog.created_at.desc()).limit(1))
            created_at = approval.created_at if approval else None
            if created_at is not None and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if (approval is None or not created_at or
                not 0 <= (datetime.now(timezone.utc) - created_at).total_seconds() <= 1200 or
                approval.actor_user_id == collector_id or
                approval.details.get("route_stop_id") != str(stop.id) or
                approval.details.get("reason") != manual_reason.strip()):
                raise PickupNotCollectableError()
            self.db.add(AuditLog(actor_user_id=collector_id, action="pickup.arrival.gps_exception_used",
                entity_type="pickup", entity_id=str(pickup.id), details={
                    "reason": manual_reason.strip()[:500], "approval_id": str(approval.id),
                    "stop_id": str(stop.id), "hospital_qr_present": True}))
        stop.status = RouteStopStatus.ARRIVED
        stop.arrived_at = stop.arrived_at or datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(stop)
        return stop

    def collect_pickup(self, *, collector_id: uuid.UUID, pickup_id: uuid.UUID,
                       token: str | None = None, actual_weight_kg: Decimal | None = None,
                       packaging_condition: str | None = None, exception_reason: str | None = None) -> PickupRequest:
        pickup = self.pickups.get_by_id(pickup_id)
        if pickup is None:
            raise PickupNotFoundError()
        if pickup.assigned_collector_id != collector_id:
            raise NotAssignedCollectorError()
        self._require_active_driver(collector_id, pickup.assigned_vehicle_id)
        if pickup.status != PickupStatus.ASSIGNED:
            raise PickupNotCollectableError()
        simulated_pickup = self.db.scalar(select(AuditLog.id).where(
            AuditLog.action == "pickup.arrival.demo_manual", AuditLog.entity_type == "pickup",
            AuditLog.entity_id == str(pickup.id)).limit(1)) is not None
        # A scanned hospital QR reference + accepted measured mass constitute
        # minimum handover evidence. The scan is not GPS proof.
        import hmac
        if not token or not hmac.compare_digest(token, pickup.handover_token):
            raise PickupNotCollectableError()
        if actual_weight_kg is None or packaging_condition not in {"sealed", "damaged", "exception"}:
            raise PickupNotCollectableError()
        try:
            actual_weight_kg = Decimal(str(actual_weight_kg))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise PickupWeightValidationError("Measured weight must be a valid positive mass in kg.") from exc
        if not actual_weight_kg.is_finite() or actual_weight_kg <= 0:
            raise PickupWeightValidationError("Measured weight must be a finite positive mass in kg.")
        route_stop = self.db.scalar(select(RouteStop).join(Route).where(
            Route.vehicle_id == pickup.assigned_vehicle_id,
            Route.status == RouteStatus.ACTIVE,
            RouteStop.pickup_id == pickup.id,
        ).limit(1).with_for_update(of=RouteStop))
        if route_stop is None or route_stop.status != RouteStopStatus.ARRIVED:
            raise PickupNotCollectableError()
        # Serialize all handovers for this vehicle. Without this lock two
        # collectors could both read the old measured load and overbook it.
        vehicle = self.db.scalar(select(Vehicle).where(
            Vehicle.id == pickup.assigned_vehicle_id,
        ).with_for_update(of=Vehicle))
        if vehicle is None or vehicle.status != VehicleStatus.ON_ROUTE:
            raise PickupNotCollectableError()
        try:
            load = check_collection_load(
                self.db, route_id=route_stop.route_id, pickup_id=pickup.id,
                actual_weight_kg=Decimal(str(actual_weight_kg)),
                capacity_kg=Decimal(str(vehicle.capacity_kg)),
            )
        except CollectionWeightError as exc:
            raise PickupWeightValidationError(str(exc)) from exc

        reason = (exception_reason or "").strip()
        if len(reason) > 500:
            raise PickupWeightValidationError("Exception explanation cannot exceed 500 characters.")
        if (load.discrepancy.has_discrepancy or packaging_condition == "exception") and len(reason) < 12:
            raise PickupWeightValidationError(
                "Measured weight differs from reported weight by at least 5%, or packaging is exceptional. "
                "Provide an explanation of at least 12 characters; collection is not recorded yet."
            )
        # All evidence, incident and chain-of-custody changes are in the same
        # DB transaction. Excess load cannot be bypassed with an explanation.
        if load.discrepancy.has_discrepancy:
            self.db.add(Incident(
                waste_record_id=pickup.items[0].waste_record_id,
                incident_type=IncidentType.WEIGHT_DISCREPANCY,
                severity=load.discrepancy.severity,
                description=(
                    f"Hospital pickup {pickup.id}: reported total {load.reported_kg:.3f} kg, "
                    f"driver measured {load.measured_kg:.3f} kg "
                    f"({load.discrepancy.variance_percent:.1f}% variance). "
                    f"Driver explanation: {reason}"
                ),
            ))
        if load.discrepancy.has_discrepancy or packaging_condition == "exception":
            self.db.add(AuditLog(
                actor_user_id=collector_id,
                action="pickup.handover.weight_exception",
                entity_type="pickup", entity_id=str(pickup.id),
                details={
                    "route_id": str(route_stop.route_id),
                    "reported_weight_kg": str(load.reported_kg),
                    "actual_weight_kg": str(load.measured_kg),
                    "variance_percent": str(round(load.discrepancy.variance_percent, 2)),
                    "packaging_condition": packaging_condition,
                    "reason": reason,
                    "projected_vehicle_load_kg": str(load.projected_load_kg),
                    "vehicle_capacity_kg": str(load.vehicle_capacity_kg),
                },
            ))
        self.db.add(CollectionProof(
            pickup_id=pickup.id, verified_by=collector_id,
            accepted_weight_kg=actual_weight_kg, packaging_condition=packaging_condition,
            acknowledgement="hospital_qr", exception_reason=reason or None,
        ))

        for item in pickup.items:
            self.records.set_status(record=item.waste_record, status=WasteStatus.COLLECTED, commit=False)
            self.events.record(
                waste_record_id=item.waste_record_id,
                event_type=WasteEventType.COLLECTED,
                status_snapshot=WasteStatus.COLLECTED,
                actor_user_id=collector_id,
                quantity=item.waste_record.quantity,
                notes=("SIMULATED: " if simulated_pickup else "") + "Collected by driver.",
                metadata={
                    "simulated": simulated_pickup,
                    "vehicle_id": str(vehicle.id),
                    "pickup_measured_weight_kg": str(load.measured_kg),
                    "pickup_reported_weight_kg": str(load.reported_kg),
                    "projected_vehicle_load_kg": str(load.projected_load_kg),
                    "weight_discrepancy_percent": str(round(load.discrepancy.variance_percent, 2)),
                },
                commit=False,
            )

        pickup.status = PickupStatus.COLLECTED
        pickup.collected_at = datetime.now(timezone.utc)
        saved = self.pickups.save(pickup, commit=False)

        # Keep the active route alive. Mark only this hospital stop complete,
        # advance the next hospital, or move the route into its destination leg.
        active_route = None
        if vehicle is not None:
            active_route = self.db.query(Route).filter(
                Route.vehicle_id == vehicle.id,
                Route.status == RouteStatus.ACTIVE,
            ).order_by(Route.version.desc()).first()
        route_topics: set[str] = set()
        if active_route is not None:
            stop = self.db.query(RouteStop).filter(
                RouteStop.route_id == active_route.id,
                RouteStop.pickup_id == pickup.id,
            ).first()
            if stop is not None:
                stop.status = RouteStopStatus.COLLECTED
                stop.completed_at = stop.completed_at or datetime.now(timezone.utc)
                stop.arrived_at = stop.arrived_at or datetime.now(timezone.utc)
            stops = self.db.query(RouteStop).filter(
                RouteStop.route_id == active_route.id
            ).order_by(RouteStop.sequence).all()
            next_stop = next((s for s in stops if s.status == RouteStopStatus.PENDING), None)
            if next_stop is not None:
                next_stop.status = RouteStopStatus.EN_ROUTE
            elif all(s.status in {RouteStopStatus.COLLECTED, RouteStopStatus.SKIPPED, RouteStopStatus.CANCELLED} for s in stops):
                active_route.destination_state = RouteDestinationState.EN_ROUTE_TO_DESTINATION.value
            self.db.flush()
            route_topics.add(route_topic(active_route.id))
        if vehicle is not None:
            # The vehicle remains on-route until the facility receipt closes the
            # transport leg. It must never become AVAILABLE at hospital collection.
            vehicle.status = VehicleStatus.ON_ROUTE
            if active_route is not None:
                route_topics.add(vehicle_topic(vehicle.id))

        self.db.commit()
        self.db.refresh(saved)

        hospital = self.hospitals.get_by_id(pickup.hospital_id)
        if hospital is not None:
            self.notifications.notify(
                user_id=hospital.user_id,
                title="Pickup collected",
                body=f"{len(pickup.items)} batch(es) have been collected and are ready for transport.",
            )

        # The hospital gets the collected state immediately; later GPS progress
        # will transition the waste to IN_TRANSIT on the destination leg.
        if route_topics:
            event = {
                "type": "status_update",
                "event": "pickup.status.updated",
                "pickup_id": str(pickup.id),
                "waste_record_ids": [str(item.waste_record_id) for item in pickup.items],
                "pickup_status": pickup.status.value,
                "waste_status": WasteStatus.COLLECTED.value,
                "vehicle_id": str(vehicle.id) if vehicle else None,
                "route_id": str(active_route.id) if active_route else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            tracking_manager.broadcast_from_sync(event, route_topics)
        return saved

    def _destination_metadata(self, record_id: uuid.UUID) -> dict:
        match = self.matches.get_confirmed_for_record(record_id)
        if not match or not match.confirmed_facility_id:
            return {"destination_type": "waste_processing_facility"}
        facility = self.db.get(TreatmentFacilityProfile, match.confirmed_facility_id)
        return {
            "destination_type": "waste_processing_facility",
            "destination_id": str(match.confirmed_facility_id),
            "destination_name": facility.name if facility else None,
            "processing_method": match.processing_method,
        }

    def _reroute_unavailable_destinations(self, pickup: PickupRequest) -> None:
        """Do NOT auto-divert a hazardous-waste vehicle to a new facility.

        Changing the confirmed destination needs a human-authorized route and
        a capacity-checked new confirmation. The prior implementation rewrote
        matching without synchronizing route geometry or locking inventory.
        """
        from app.services.organization_eligibility import eligible_facility
        for item in pickup.items:
            match = self.matches.get_confirmed_for_record(item.waste_record_id)
            facility = (self.db.get(TreatmentFacilityProfile, match.confirmed_facility_id)
                        if match and match.confirmed_facility_id else None)
            if not eligible_facility(self.db, facility,
                    need_capability=match.processing_method if match else None):
                raise DestinationNotConfirmedError(item.waste_record.waste_code)

    def start_transit(self, *, collector_id: uuid.UUID, pickup_id: uuid.UUID) -> PickupRequest:
        pickup = self.pickups.get_by_id(pickup_id)
        if pickup is None:
            raise PickupNotFoundError()
        if pickup.assigned_collector_id != collector_id:
            raise NotAssignedCollectorError()
        self._require_active_driver(collector_id, pickup.assigned_vehicle_id)
        if pickup.status != PickupStatus.COLLECTED:
            raise PickupNotInTransitableError()
        simulated_pickup = self.db.scalar(select(AuditLog.id).where(
            AuditLog.action == "pickup.arrival.demo_manual", AuditLog.entity_type == "pickup",
            AuditLog.entity_id == str(pickup.id)).limit(1)) is not None
        # No independent transport leg without a started, verified route.
        active_route = self.db.scalar(select(Route).join(RouteStop,
            RouteStop.route_id == Route.id).where(
            RouteStop.pickup_id == pickup_id,
            Route.status == RouteStatus.ACTIVE,
            Route.vehicle_id == pickup.assigned_vehicle_id).limit(1).with_for_update(of=Route))
        if active_route is None or active_route.destination_state not in {
            RouteDestinationState.EN_ROUTE_TO_DESTINATION.value,
            RouteDestinationState.AT_DESTINATION.value,
        }:
            raise PickupNotInTransitableError()
        remaining_stops = list(self.db.scalars(select(RouteStop).where(
            RouteStop.route_id == active_route.id)).all())
        if any(s.status not in {RouteStopStatus.COLLECTED,
                RouteStopStatus.SKIPPED, RouteStopStatus.CANCELLED} for s in remaining_stops):
            raise PickupNotInTransitableError()

        self._reroute_unavailable_destinations(pickup)

        for item in pickup.items:
            if item.waste_record.status == WasteStatus.COLLECTED:
                self.records.set_status(record=item.waste_record, status=WasteStatus.IN_TRANSIT)
                self.events.record(
                    waste_record_id=item.waste_record_id,
                    event_type=WasteEventType.IN_TRANSIT,
                    status_snapshot=WasteStatus.IN_TRANSIT,
                    actor_user_id=collector_id,
                    quantity=item.waste_record.quantity,
                    notes=("SIMULATED: " if simulated_pickup else "") + "In transit to the assigned Waste Processing Facility.",
                    metadata={**self._destination_metadata(item.waste_record_id), "simulated": simulated_pickup},
                )

        pickup.status = PickupStatus.IN_TRANSIT
        saved = self.pickups.save(pickup)
        return saved