
import hmac
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.db import get_db
from app.models.audit_log import AuditLog
from app.models.pickup_request import PickupRequest, PickupRequestItem
from app.models.roles import UserRole
from app.models.route import (
    Route, RouteStatus, RouteStop, RouteStopStatus,
    RouteDestinationState,
)
from app.models.user import User
from app.models.waste_enums import (
    PickupStatus, WasteStatus, WasteEventType,
)
from app.repositories.facility_repository import FacilityRepository
from app.repositories.matching_repository import MatchingRepository
from app.services.pickup_service import (
    PickupService, NotAssignedCollectorError,
)
from app.services.receiving_service import (
    ReceivingService,
    OrgProfileRequiredError,
    WasteRecordNotFoundError,
    NotConfirmedDestinationError,
    NotInTransitError,
    DestinationArrivalRequiredError,
)
from app.services.waste_event_service import WasteEventService

router = APIRouter(
    prefix="/manual-workflow",
    tags=["manual-workflow"],
)


class ManualArrival(BaseModel):
    handover_qr: str = Field(min_length=20, max_length=128)
    note: str = Field(min_length=12, max_length=500)
    confirm_hospital_presence: bool


class ManualReceipt(BaseModel):
    received_quantity: Decimal = Field(
        gt=0,
        max_digits=12,
        decimal_places=3,
    )
    note: str = Field(min_length=12, max_length=500)
    confirm_physical_receipt: bool


@router.get("/pickups/{pickup_id}/state")
def manual_pickup_state(
    pickup_id: UUID,
    user: User = Depends(require_roles(UserRole.COLLECTOR)),
    db: Session = Depends(get_db),
):
    pickup = db.get(PickupRequest, pickup_id)

    if pickup is None or pickup.assigned_collector_id != user.id:
        raise HTTPException(
            403, "Pickup is not assigned to this driver."
        )

    stop = db.scalar(
        select(RouteStop)
        .join(Route, Route.id == RouteStop.route_id)
        .where(
            RouteStop.pickup_id == pickup_id,
            Route.vehicle_id == pickup.assigned_vehicle_id,
            Route.status == RouteStatus.ACTIVE,
        )
        .limit(1)
    )

    arrived = (
        bool(
            stop and stop.status in {
                RouteStopStatus.ARRIVED,
                RouteStopStatus.COLLECTED,
            }
        )
        or pickup.status in {
            PickupStatus.COLLECTED,
            PickupStatus.IN_TRANSIT,
            PickupStatus.COMPLETED,
        }
    )

    return {
        "pickup_status": pickup.status.value,
        "stop_status": stop.status.value if stop else None,
        "arrived": arrived,
        "collected": pickup.status in {
            PickupStatus.COLLECTED,
            PickupStatus.IN_TRANSIT,
            PickupStatus.COMPLETED,
        },
        "in_transit": pickup.status in {
            PickupStatus.IN_TRANSIT,
            PickupStatus.COMPLETED,
        },
    }


@router.post("/pickups/{pickup_id}/arrival")
def manual_hospital_arrival(
    pickup_id: UUID,
    payload: ManualArrival,
    user: User = Depends(require_roles(UserRole.COLLECTOR)),
    db: Session = Depends(get_db),
):
    if not payload.confirm_hospital_presence:
        raise HTTPException(
            422,
            "Driver must explicitly attest hospital presence.",
        )

    pickup = db.scalar(
        select(PickupRequest)
        .where(PickupRequest.id == pickup_id)
        .with_for_update(of=PickupRequest)
    )

    if pickup is None or pickup.assigned_collector_id != user.id:
        raise HTTPException(
            403, "This pickup is not assigned to this driver."
        )

    if (
        pickup.status != PickupStatus.ASSIGNED
        or pickup.assigned_vehicle_id is None
    ):
        raise HTTPException(
            409, "Pickup must be assigned before manual arrival."
        )

    try:
        PickupService(db)._require_active_driver(
            user.id, pickup.assigned_vehicle_id
        )
    except NotAssignedCollectorError:
        raise HTTPException(
            403,
            "The assigned vehicle or active driver membership does not match.",
        )

    if (
        not pickup.handover_token
        or not hmac.compare_digest(
            str(pickup.handover_token),
            payload.handover_qr,
        )
    ):
        raise HTTPException(
            403, "Incorrect hospital handover QR reference."
        )

    stop = db.scalar(
        select(RouteStop)
        .join(Route, Route.id == RouteStop.route_id)
        .where(
            RouteStop.pickup_id == pickup_id,
            Route.vehicle_id == pickup.assigned_vehicle_id,
            Route.status == RouteStatus.ACTIVE,
        )
        .limit(1)
        .with_for_update(of=RouteStop)
    )

    if stop is None or stop.status != RouteStopStatus.EN_ROUTE:
        raise HTTPException(
            409,
            "An active route with an EN_ROUTE hospital stop is required.",
        )

    now = datetime.now(timezone.utc)

    stop.status = RouteStopStatus.ARRIVED
    stop.arrived_at = now

    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="pickup.arrival.driver_attested",
            entity_type="pickup",
            entity_id=str(pickup_id),
            details={
                "route_id": str(stop.route_id),
                "driver_id": str(user.id),
                "method": "driver_attestation_plus_hospital_qr",
                "gps_verified": False,
                "independently_verified": False,
                "note": payload.note.strip(),
                "time": now.isoformat(),
            },
        )
    )

    for item in pickup.items:
        WasteEventService(db).record(
            waste_record_id=item.waste_record_id,
            event_type=WasteEventType.PICKUP_ASSIGNED,
            status_snapshot=WasteStatus.PICKUP_ASSIGNED,
            actor_user_id=user.id,
            quantity=item.waste_record.quantity,
            notes=(
                "Driver manually declared hospital arrival "
                "with handover QR; GPS not verified."
            ),
            metadata={
                "manual_arrival": True,
                "gps_verified": False,
                "driver_id": str(user.id),
                "pickup_id": str(pickup_id),
            },
            commit=False,
        )

    db.commit()

    return {
        "status": "arrived",
        "confirmation_method": "driver_attested",
        "gps_verified": False,
        "pickup_id": str(pickup_id),
    }


@router.post("/waste/{record_id}/receipt")
def manually_confirm_facility_receipt(
    record_id: UUID,
    payload: ManualReceipt,
    user: User = Depends(require_roles(UserRole.FACILITY)),
    db: Session = Depends(get_db),
):
    if not payload.confirm_physical_receipt:
        raise HTTPException(
            422,
            "Facility receiver must explicitly attest physical receipt.",
        )

    profile = FacilityRepository(db).get_by_user_id(user.id)

    if profile is None:
        raise HTTPException(
            412, "Create/link a treatment facility profile first."
        )

    match = MatchingRepository(db).get_confirmed_for_record(
        record_id
    )

    if (
        match is None
        or match.confirmed_facility_id != profile.id
    ):
        raise HTTPException(
            403, "This record is not assigned to your facility."
        )

    route = db.scalar(
        select(Route)
        .join(RouteStop, RouteStop.route_id == Route.id)
        .join(
            PickupRequest,
            PickupRequest.id == RouteStop.pickup_id,
        )
        .join(
            PickupRequestItem,
            PickupRequestItem.pickup_request_id == PickupRequest.id,
        )
        .where(
            PickupRequestItem.waste_record_id == record_id,
            PickupRequest.status == PickupStatus.IN_TRANSIT,
            Route.status == RouteStatus.ACTIVE,
        )
        .order_by(Route.version.desc())
        .limit(1)
        .with_for_update(of=Route)
    )

    if (
        route is None
        or route.destination_state
        != RouteDestinationState.EN_ROUTE_TO_DESTINATION.value
    ):
        raise HTTPException(
            409,
            "The assigned vehicle must first start transit to this facility.",
        )

    now = datetime.now(timezone.utc)

    route.destination_state = (
        RouteDestinationState.AT_DESTINATION.value
    )
    route.destination_arrived_at = now

    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="facility.receipt.staff_attested",
            entity_type="waste",
            entity_id=str(record_id),
            details={
                "route_id": str(route.id),
                "facility_id": str(profile.id),
                "receiver_id": str(user.id),
                "gps_verified": False,
                "note": payload.note.strip(),
                "time": now.isoformat(),
            },
        )
    )

    db.flush()

    try:
        result = ReceivingService(db).confirm_receipt(
            user_id=user.id,
            record_id=record_id,
            received_quantity=payload.received_quantity,
        )

    except OrgProfileRequiredError:
        db.rollback()
        raise HTTPException(
            412, "Complete and link the facility profile first."
        )

    except (
        NotConfirmedDestinationError,
        WasteRecordNotFoundError,
    ):
        db.rollback()
        raise HTTPException(
            403, "Record or facility is not eligible for receipt."
        )

    except (
        NotInTransitError,
        DestinationArrivalRequiredError,
    ):
        db.rollback()
        raise HTTPException(
            409, "Waste is not eligible for manual receipt yet."
        )

    return result
