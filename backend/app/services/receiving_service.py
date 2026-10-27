
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.business import EventOutbox
from app.models.waste_enums import (
    IncidentType,
    WasteEventType,
    WasteStatus,
    PickupStatus,
    VehicleStatus,
)
from app.models.route import Route, RouteStatus, RouteDestinationState
from app.models.tracking import TrackingSession, TrackingSessionStatus
from app.models.pickup_request import PickupRequest, PickupRequestItem
from app.repositories.facility_repository import FacilityRepository
from app.repositories.hospital_repository import HospitalRepository
from app.models.hospital_profile import HospitalProfile
from app.repositories.incident_repository import IncidentRepository
from app.repositories.matching_repository import MatchingRepository
from app.repositories.waste_record_repository import WasteRecordRepository
from app.rules.discrepancy_rules import detect_discrepancy
from app.schemas.transport import ReceiveWasteResponse
from app.services.waste_event_service import WasteEventService
from app.realtime.tracking_manager import (
    route_topic,
    tracking_manager,
    vehicle_topic,
)


class OrgProfileRequiredError(Exception):
    pass


class WasteRecordNotFoundError(Exception):
    pass


class NotConfirmedDestinationError(Exception):
    pass


class NotInTransitError(Exception):
    pass


class DestinationArrivalRequiredError(Exception):
    pass


class ReceivingService:
    """Receipt workflow for the unified Waste Processing Facility role."""

    def __init__(self, db: Session):
        self.db = db
        self.records = WasteRecordRepository(db)
        self.facilities = FacilityRepository(db)
        self.matches = MatchingRepository(db)
        self.hospitals = HospitalRepository(db)
        self.incidents = IncidentRepository(db)
        self.events = WasteEventService(db)

    def _own_profile(self, *, user_id: uuid.UUID):
        profile = self.facilities.get_by_user_id(user_id)
        if profile is None:
            raise OrgProfileRequiredError()
        return profile

    def list_incoming(self, *, user_id: uuid.UUID):
        profile = self._own_profile(user_id=user_id)
        return self.records.list_incoming_for_facility(profile.id)

    def _complete_transport_if_ready(
        self, record_id: uuid.UUID, received_at
    ) -> tuple[
        list[tuple[Route, object]],
        list[tuple[Route, PickupRequest]],
    ]:
        """Complete pickups/routes only after every batch is received."""
        from app.models.route import RouteStop, RouteStopStatus
        from app.models.vehicle import Vehicle

        received_states = {
            WasteStatus.DESTINATION_RECEIVED,
            WasteStatus.PROCESSING,
            WasteStatus.PROOF_SUBMITTED,
            WasteStatus.VERIFIED,
            WasteStatus.COMPLETED,
        }

        routes = list(
            self.db.scalars(
                select(Route)
                .join(RouteStop, RouteStop.route_id == Route.id)
                .join(
                    PickupRequest,
                    PickupRequest.id == RouteStop.pickup_id,
                )
                .join(
                    PickupRequestItem,
                    PickupRequestItem.pickup_request_id
                    == PickupRequest.id,
                )
                .where(
                    PickupRequestItem.waste_record_id == record_id,
                    Route.status == RouteStatus.ACTIVE,
                )
            ).unique().all()
        )

        completed_routes = []
        completed_pickups = []

        for route in routes:
            stops = list(
                self.db.scalars(
                    select(RouteStop).where(
                        RouteStop.route_id == route.id
                    )
                ).all()
            )

            route_ready = bool(stops)
            delivered_count = 0

            for stop in stops:
                pickup = self.db.get(
                    PickupRequest, stop.pickup_id
                )

                if pickup is None:
                    route_ready = False
                    continue

                if stop.status in {
                    RouteStopStatus.CANCELLED,
                    RouteStopStatus.SKIPPED,
                }:
                    if (
                        pickup.status != PickupStatus.CANCELLED
                        or any(
                            item.waste_record is not None
                            and item.waste_record.status
                            in {
                                WasteStatus.COLLECTED,
                                WasteStatus.IN_TRANSIT,
                                *received_states,
                            }
                            for item in pickup.items
                        )
                    ):
                        route_ready = False
                    continue

                if pickup.status == PickupStatus.CANCELLED:
                    route_ready = False
                    continue

                if not pickup.items:
                    route_ready = False
                    continue

                batches_received = all(
                    item.waste_record is not None
                    and item.waste_record.status in received_states
                    for item in pickup.items
                )

                if (
                    batches_received
                    and pickup.status == PickupStatus.IN_TRANSIT
                ):
                    pickup.status = PickupStatus.COMPLETED
                    completed_pickups.append((route, pickup))

                if (
                    not batches_received
                    or pickup.status != PickupStatus.COMPLETED
                ):
                    route_ready = False
                else:
                    delivered_count += 1

            route_ready = (
                route_ready and delivered_count > 0
            )

            if route_ready:
                route.destination_state = (
                    RouteDestinationState.COMPLETED.value
                )
                route.destination_received_at = (
                    route.destination_received_at or received_at
                )
                route.status = RouteStatus.COMPLETED
                route.completed_at = (
                    route.completed_at or received_at
                )

                if route.tracking_session_id:
                    session = self.db.get(
                        TrackingSession,
                        route.tracking_session_id,
                    )

                    if (
                        session
                        and session.status not in {
                            TrackingSessionStatus.COMPLETED,
                            TrackingSessionStatus.CANCELLED,
                        }
                    ):
                        session.status = (
                            TrackingSessionStatus.COMPLETED
                        )
                        session.ended_at = received_at

                vehicle = self.db.get(
                    Vehicle, route.vehicle_id
                )

                if vehicle:
                    pending = self.db.scalar(
                        select(PickupRequest.id)
                        .where(
                            PickupRequest.assigned_vehicle_id
                            == vehicle.id,
                            PickupRequest.status
                            == PickupStatus.ASSIGNED,
                        )
                        .limit(1)
                    )

                    vehicle.status = (
                        VehicleStatus.RESERVED
                        if pending
                        else VehicleStatus.AVAILABLE
                    )

                completed_routes.append((route, vehicle))

        return completed_routes, completed_pickups

    def confirm_receipt(
        self,
        *,
        user_id: uuid.UUID,
        record_id: uuid.UUID,
        received_quantity: Decimal | None,
        demo_manual_receipt: bool = False,
    ) -> ReceiveWasteResponse:
        from app.models.waste_record import WasteRecord
        from app.models.route import RouteStop
        from app.models.audit_log import AuditLog
        from app.core.config import get_settings
        from app.services.organization_eligibility import (
            eligible_facility,
            can_profile_action,
        )
        from datetime import datetime, timezone

        profile = self._own_profile(user_id=user_id)

        if not can_profile_action(
            self.db,
            profile,
            user_id,
            "TREATMENT_FACILITY",
            "facility_receive",
        ):
            raise NotConfirmedDestinationError()

        if not eligible_facility(self.db, profile):
            raise NotConfirmedDestinationError()

        record = self.db.scalar(
            select(WasteRecord)
            .where(WasteRecord.id == record_id)
            .with_for_update(of=WasteRecord)
            .execution_options(populate_existing=True)
        )

        if record is None:
            raise WasteRecordNotFoundError()

        match = self.matches.get_confirmed_for_record(
            record_id
        )

        if (
            match is None
            or match.confirmed_facility_id != profile.id
        ):
            raise NotConfirmedDestinationError()

        if record.status != WasteStatus.IN_TRANSIT:
            raise NotInTransitError()

        # Locate the active route for this waste batch.
        route = self.db.scalar(
            select(Route)
            .join(
                RouteStop,
                RouteStop.route_id == Route.id,
            )
            .join(
                PickupRequest,
                PickupRequest.id == RouteStop.pickup_id,
            )
            .join(
                PickupRequestItem,
                PickupRequestItem.pickup_request_id
                == PickupRequest.id,
            )
            .where(
                PickupRequestItem.waste_record_id
                == record_id,
                Route.status == RouteStatus.ACTIVE,
            )
            .order_by(Route.version.desc())
            .limit(1)
            .with_for_update(of=Route)
        )

        # Preserve independently approved exceptions.
        approved = self.db.scalar(
            select(AuditLog)
            .where(
                AuditLog.action
                == "facility.receipt.exception_approved",
                AuditLog.entity_type == "waste",
                AuditLog.entity_id == str(record_id),
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )

        approval_time = (
            approved.created_at if approved else None
        )

        if (
            approval_time is not None
            and approval_time.tzinfo is None
        ):
            approval_time = approval_time.replace(
                tzinfo=timezone.utc
            )

        valid_override = bool(
            approved
            and approved.actor_user_id != user_id
            and approval_time
            and 0 <= (
                datetime.now(timezone.utc) - approval_time
            ).total_seconds() <= 1200
            and (approved.details or {}).get("facility_id")
            == str(profile.id)
        )

        # Keep support for the previous local demo workflow.
        cfg = get_settings()

        demo_allowed = bool(
            demo_manual_receipt
            and cfg.enable_demo_manual_workflow
            and cfg.environment.lower()
            in {"development", "test"}
            and route is not None
            and route.destination_state
            == RouteDestinationState
            .EN_ROUTE_TO_DESTINATION.value
            and route.destination_latitude is not None
            and route.destination_longitude is not None
        )

        # Manual facility receipt creates an audit event
        # before calling this service.
        # This records provenance; it does not bypass
        # permission, destination or transport checks.
        manual_audit = self.db.scalar(
            select(AuditLog)
            .where(
                AuditLog.action
                == "facility.receipt.staff_attested",
                AuditLog.entity_type == "waste",
                AuditLog.entity_id == str(record_id),
                AuditLog.actor_user_id == user_id,
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )

        manual_attested = bool(
            route is not None
            and manual_audit is not None
            and (manual_audit.details or {}).get("route_id")
            == str(route.id)
            and (manual_audit.details or {}).get("facility_id")
            == str(profile.id)
        )

        if demo_manual_receipt and not demo_allowed:
            raise DestinationArrivalRequiredError()

        destination_arrived = bool(
            route
            and route.destination_state
            == RouteDestinationState.AT_DESTINATION.value
            and route.destination_arrived_at is not None
        )

        if (
            not destination_arrived
            and not valid_override
            and not demo_allowed
        ):
            raise DestinationArrivalRequiredError()

        if valid_override:
            self.db.add(
                AuditLog(
                    actor_user_id=user_id,
                    action="facility.receipt.exception_used",
                    entity_type="waste",
                    entity_id=str(record_id),
                    details={
                        "approval_id": str(approved.id),
                        "facility_id": str(profile.id),
                    },
                )
            )

        if demo_allowed:
            self.db.add(
                AuditLog(
                    actor_user_id=user_id,
                    action="facility.receipt.demo_manual",
                    entity_type="waste",
                    entity_id=str(record_id),
                    details={
                        "simulated": True,
                        "route_id": str(route.id),
                        "facility_id": str(profile.id),
                        "no_gps_arrival_claim": True,
                    },
                )
            )

        final_quantity = (
            received_quantity
            if received_quantity is not None
            else record.quantity
        )

        record = self.records.record_receipt(
            record=record,
            received_quantity=final_quantity,
            received_by=user_id,
            status=WasteStatus.DESTINATION_RECEIVED,
            commit=False,
        )

        result = detect_discrepancy(
            reported_quantity=Decimal(
                str(record.quantity)
            ),
            received_quantity=Decimal(
                str(final_quantity)
            ),
        )

        incident = None

        if result.has_discrepancy:
            incident = self.incidents.create(
                Incident(
                    waste_record_id=record.id,
                    incident_type=(
                        IncidentType.WEIGHT_DISCREPANCY
                    ),
                    severity=result.severity,
                    description=result.description,
                ),
                commit=False,
            )

        # Event is visible in the waste timeline.
        if manual_attested:
            receipt_prefix = (
                "Manual facility receipt "
                "(staff attestation; GPS not verified): "
            )
        elif demo_allowed:
            receipt_prefix = "SIMULATED receipt: "
        else:
            receipt_prefix = ""

        self.events.record(
            waste_record_id=record.id,
            event_type=WasteEventType.DESTINATION_RECEIVED,
            status_snapshot=(
                WasteStatus.DESTINATION_RECEIVED
            ),
            actor_user_id=user_id,
            quantity=final_quantity,
            notes=(
                f"{receipt_prefix}Received by "
                f"{profile.name}. {result.description}"
            ),
            metadata={
                "simulated": demo_allowed,
                "manual_facility_receipt": manual_attested,
                "gps_verified": (
                    False if manual_attested else None
                ),
                "destination_name": profile.name,
                "destination_type": (
                    "waste_processing_facility"
                ),
                "variance_percent": str(
                    round(result.variance_percent, 1)
                ),
                "processing_method": (
                    match.processing_method
                ),
            },
            commit=False,
        )

        received_at = record.received_at

        completed_routes, completed_pickups = (
            self._complete_transport_if_ready(
                record.id, received_at
            )
        )

        # Store notification intent transactionally.
        if (
            record.hospital_id
            and self.db.get(
                HospitalProfile,
                record.hospital_id,
            )
        ):
            self.db.add(
                EventOutbox(
                    dedupe_key=(
                        "facility-receipt-notification:"
                        f"{record.id}"
                    ),
                    topic="notification.facility.received",
                    payload={
                        "record_id": str(record.id),
                        "facility_id": str(profile.id),
                    },
                )
            )

        self.db.commit()

        # Broadcast completed pickup status.
        for completed_route, pickup in completed_pickups:
            tracking_manager.broadcast_from_sync(
                {
                    "type": "status_update",
                    "event": "pickup.status.updated",
                    "pickup_id": str(pickup.id),
                    "pickup_status": (
                        PickupStatus.COMPLETED.value
                    ),
                    "waste_record_ids": [
                        str(item.waste_record_id)
                        for item in pickup.items
                    ],
                    "route_id": str(completed_route.id),
                    "vehicle_id": str(
                        completed_route.vehicle_id
                    ),
                    "timestamp": (
                        received_at.isoformat()
                        if received_at
                        else None
                    ),
                },
                {
                    route_topic(completed_route.id),
                    vehicle_topic(
                        completed_route.vehicle_id
                    ),
                },
            )

        tracking_topics = set()

        for completed_route, vehicle in completed_routes:
            tracking_topics.add(
                route_topic(completed_route.id)
            )

            if vehicle:
                tracking_topics.add(
                    vehicle_topic(vehicle.id)
                )

            tracking_manager.broadcast_from_sync(
                {
                    "type": "status_update",
                    "event": "route.completed",
                    "route_id": str(completed_route.id),
                    "vehicle_id": str(
                        completed_route.vehicle_id
                    ),
                    "destination_state": (
                        completed_route.destination_state
                    ),
                    "timestamp": (
                        received_at.isoformat()
                        if received_at
                        else None
                    ),
                },
                {
                    route_topic(completed_route.id),
                    vehicle_topic(
                        completed_route.vehicle_id
                    ),
                },
            )

        # Notify authorized route/vehicle subscribers.
        route_for_record = self.db.scalar(
            select(Route)
            .join(
                RouteStop,
                RouteStop.route_id == Route.id,
            )
            .join(
                PickupRequest,
                PickupRequest.id == RouteStop.pickup_id,
            )
            .join(
                PickupRequestItem,
                PickupRequestItem.pickup_request_id
                == PickupRequest.id,
            )
            .where(
                PickupRequestItem.waste_record_id
                == record.id
            )
            .order_by(Route.version.desc())
        )

        receipt_topics = set(tracking_topics)

        if route_for_record:
            receipt_topics.update(
                {
                    route_topic(route_for_record.id),
                    vehicle_topic(
                        route_for_record.vehicle_id
                    ),
                }
            )

        tracking_manager.broadcast_from_sync(
            {
                "type": "status_update",
                "event": "destination.received",
                "waste_record_id": str(record.id),
                "facility_id": str(profile.id),
                "waste_status": record.status.value,
                "timestamp": (
                    received_at.isoformat()
                    if received_at
                    else None
                ),
            },
            receipt_topics,
        )

        return ReceiveWasteResponse(
            waste_record_id=record.id,
            received_quantity=final_quantity,
            reported_quantity=Decimal(
                str(record.quantity)
            ),
            variance_percent=Decimal(
                str(round(result.variance_percent, 1))
            ),
            incident=incident,
        )
