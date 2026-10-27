import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.waste_enums import PickupPriority, PickupStatus
from app.models.hospital_profile import HospitalProfile
from app.schemas.vehicle import VehicleResponse
from app.schemas.waste import WasteRecordResponse
from app.services.quantity_service import quantity_to_kg


class PickupRequestCreate(BaseModel):
    waste_record_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    priority: PickupPriority = PickupPriority.NORMAL
    notes: str | None = Field(default=None, max_length=1000)
    requested_pickup_at: datetime | None = None
    requested_pickup_end_at: datetime | None = None


class PickupCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class PickupHospitalSummary(BaseModel):
    id: uuid.UUID
    name: str
    address_line: str
    city: str
    region: str
    postal_code: str
    latitude: Decimal | None
    longitude: Decimal | None


class PickupRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hospital_id: uuid.UUID
    priority: PickupPriority
    status: PickupStatus
    requested_pickup_at: datetime | None
    requested_pickup_end_at: datetime | None = None
    scheduled_at: datetime | None
    assigned_vehicle: VehicleResponse | None
    hospital: PickupHospitalSummary
    total_weight_kg: Decimal | None
    route_eligible: bool
    route_ineligibility_reason: str | None
    assigned_collector_id: uuid.UUID | None
    collected_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    waste_records: list[WasteRecordResponse]


class PickupRequestListResponse(BaseModel):
    items: list[PickupRequestResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


def _waste_response(record, db=None):
    payload = WasteRecordResponse.model_validate(record).model_dump()
    if db is not None:
        from app.repositories.matching_repository import MatchingRepository
        match = MatchingRepository(db).get_confirmed_for_record(record.id)
        if match and match.confirmed_facility_id:
            payload["assigned_facility_id"] = match.confirmed_facility_id
            payload["processing_method"] = match.processing_method
            for candidate in match.candidates or []:
                if candidate.get("id") == str(match.confirmed_facility_id):
                    payload["assigned_facility_name"] = candidate.get("name")
                    payload["processing_method"] = candidate.get("processing_method") or match.processing_method
                    break
    return WasteRecordResponse.model_validate(payload)


def pickup_to_response(pickup, db=None) -> PickupRequestResponse:
    """Builds the response schema from the ORM model — needed because the
    API shape (`waste_records`) doesn't map 1:1 onto the join table
    (`items[].waste_record`)."""
    hospital = db.get(HospitalProfile, pickup.hospital_id) if db is not None else None
    quantities = [
        quantity_to_kg(item.waste_record.quantity, item.waste_record.unit)
        for item in pickup.items
    ]
    total_weight = sum((value for value in quantities if value is not None), Decimal("0"))
    route_eligible = pickup.status in {
        PickupStatus.ASSIGNED,
        PickupStatus.COLLECTED,
        PickupStatus.IN_TRANSIT,
    } and pickup.assigned_vehicle_id is not None and pickup.assigned_collector_id is not None
    reason = None
    if not route_eligible:
        if pickup.status == PickupStatus.CANCELLED:
            reason = "Cancelled pickups cannot be added to a route."
        elif pickup.assigned_vehicle_id is None:
            reason = "This pickup has not been assigned to a vehicle yet."
        else:
            reason = f"Pickup status is {pickup.status.value.replace('_', ' ')}."

    return PickupRequestResponse(
        id=pickup.id,
        hospital_id=pickup.hospital_id,
        priority=pickup.priority,
        status=pickup.status,
        requested_pickup_at=pickup.requested_pickup_at,
        requested_pickup_end_at=pickup.requested_pickup_end_at,
        scheduled_at=pickup.scheduled_at,
        assigned_vehicle=(
            VehicleResponse.model_validate(pickup.assigned_vehicle)
            if pickup.assigned_vehicle
            else None
        ),
        hospital=PickupHospitalSummary(
            id=hospital.id if hospital else pickup.hospital_id,
            name=hospital.name if hospital else "Hospital",
            address_line=hospital.address_line if hospital else "",
            city=hospital.city if hospital else "",
            region=hospital.region if hospital else "",
            postal_code=hospital.postal_code if hospital else "",
            latitude=hospital.latitude if hospital else None,
            longitude=hospital.longitude if hospital else None,
        ),
        total_weight_kg=total_weight,
        route_eligible=route_eligible,
        route_ineligibility_reason=reason,
        assigned_collector_id=pickup.assigned_collector_id,
        collected_at=pickup.collected_at,
        cancelled_at=pickup.cancelled_at,
        cancellation_reason=pickup.cancellation_reason,
        notes=pickup.notes,
        created_at=pickup.created_at,
        updated_at=pickup.updated_at,
        waste_records=[_waste_response(item.waste_record, db) for item in pickup.items],
    )
