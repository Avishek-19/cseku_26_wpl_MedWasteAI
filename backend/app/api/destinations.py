from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.route import Route, RouteStop
from app.models.pickup_request import PickupRequest, PickupRequestItem
from app.models.user import User
from app.schemas.transport import ReceiveWasteRequest, ReceiveWasteResponse
from app.schemas.waste import WasteRecordResponse
from app.services.receiving_service import (
    NotConfirmedDestinationError,
    NotInTransitError,
    OrgProfileRequiredError,
    ReceivingService,
    DestinationArrivalRequiredError,
    WasteRecordNotFoundError,
)

router = APIRouter(prefix="/destinations", tags=["destinations"])
require_destination_org = require_roles(UserRole.FACILITY)


def _profile_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_412_PRECONDITION_FAILED,
        detail="Complete your Waste Processing Facility profile first.",
    )


@router.get("/incoming", response_model=list[WasteRecordResponse])
def list_incoming(
    current_user: User = Depends(require_destination_org), db: Session = Depends(get_db)
):
    try:
        records = ReceivingService(db).list_incoming(user_id=current_user.id)
        from app.repositories.matching_repository import MatchingRepository
        matches = MatchingRepository(db)
        result = []
        for record in records:
            item = WasteRecordResponse.model_validate(record).model_dump(mode="json")
            match = matches.get_confirmed_for_record(record.id)
            if match and match.confirmed_facility_id:
                item["assigned_facility_id"] = str(match.confirmed_facility_id)
                item["processing_method"] = match.processing_method
                for candidate in match.candidates or []:
                    if candidate.get("id") == str(match.confirmed_facility_id):
                        item["assigned_facility_name"] = candidate.get("name")
                        item["processing_method"] = candidate.get("processing_method") or match.processing_method
                        break
            route = db.scalar(
                select(Route)
                .join(RouteStop, RouteStop.route_id == Route.id)
                .join(PickupRequest, PickupRequest.id == RouteStop.pickup_id)
                .join(PickupRequestItem, PickupRequestItem.pickup_request_id == PickupRequest.id)
                .where(PickupRequestItem.waste_record_id == record.id)
                .order_by(Route.version.desc())
            )
            if route:
                item["route_id"] = str(route.id)
                item["vehicle_id"] = str(route.vehicle_id)
            result.append(item)
        return result
    except OrgProfileRequiredError:
        raise _profile_required()


@router.get("/facility-profile")
def facility_profile_summary(current_user: User = Depends(require_destination_org), db: Session = Depends(get_db)):
    from app.services.facility_service import FacilityService
    profile = FacilityService(db).get_profile(current_user.id)
    if profile is None:
        raise _profile_required()
    return {
        "id": profile.id,
        "name": profile.name,
        "facility_type": profile.facility_type,
        "processing_services": profile.processing_services or [],
        "other_services": profile.other_services or [],
        "availability_status": profile.availability_status,
        "is_verified": profile.is_verified,
        "capacity_kg": profile.capacity_kg,
        "current_utilization_kg": profile.current_utilization_kg,
        "available_capacity_kg": profile.available_capacity_kg,
    }


@router.post("/{record_id}/receive", response_model=ReceiveWasteResponse)
def receive_waste(
    record_id: UUID,
    payload: ReceiveWasteRequest,
    current_user: User = Depends(require_destination_org),
    db: Session = Depends(get_db),
):
    try:
        return ReceivingService(db).confirm_receipt(
            user_id=current_user.id,
            record_id=record_id,
            received_quantity=payload.received_quantity,
            demo_manual_receipt=payload.demo_manual_receipt,
        )
    except OrgProfileRequiredError:
        raise _profile_required()
    except WasteRecordNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waste record not found.")
    except NotConfirmedDestinationError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This batch isn't assigned to your Waste Processing Facility.")
    except NotInTransitError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This batch isn't in transit yet.")
    except DestinationArrivalRequiredError:
        raise HTTPException(status_code=409, detail="Verified facility destination arrival or an approved exception is required.")