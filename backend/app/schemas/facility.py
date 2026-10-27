import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class FacilityProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    registration_number: str = Field(min_length=1, max_length=100)
    contact_person: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=1, max_length=30)
    address_line: str = Field(min_length=1, max_length=255)
    city: str = Field(min_length=1, max_length=120)
    region: str = Field(min_length=1, max_length=120)
    postal_code: str = Field(min_length=1, max_length=20)
    capacity_kg: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    facility_type: str = Field(default="Waste Processing Facility", min_length=1, max_length=80)
    processing_services: list[str] = Field(default_factory=list, max_length=20)
    other_services: list[str] = Field(default_factory=list, max_length=20)
    availability_status: str = Field(default="available", pattern="^(available|limited|unavailable)$")
    accepted_category_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    # Optional WGS84 coordinates used by route optimization
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class FacilityProfileUpdate(FacilityProfileCreate):
    pass


class FacilityProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    registration_number: str
    contact_person: str
    phone: str
    address_line: str
    city: str
    region: str
    postal_code: str
    capacity_kg: Decimal
    current_utilization_kg: Decimal
    available_capacity_kg: Decimal
    is_verified: bool
    facility_type: str
    processing_services: list[str]
    other_services: list[str]
    availability_status: str
    latitude: float | None = None
    longitude: float | None = None
    created_at: datetime
    updated_at: datetime


class AcceptedCategoriesUpdate(BaseModel):
    category_ids: list[uuid.UUID] = Field(max_length=20)


class FacilityDashboardStats(BaseModel):
    profile_complete: bool
    is_verified: bool
    facility_type: str
    processing_services: list[str]
    other_services: list[str]
    availability_status: str
    member_since: datetime
    capacity_kg: Decimal | None
    current_utilization_kg: Decimal | None
    available_capacity_kg: Decimal | None
    utilization_percent: float | None
    accepted_category_count: int

    # Populated once destination matching exists (Phase 9 onward).
    incoming_waste_count: int = 0
    matching_available: bool = False
    processing_queue_count: int = 0