import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class HospitalProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    registration_number: str = Field(min_length=1, max_length=100)
    contact_person: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=1, max_length=30)
    address_line: str = Field(min_length=1, max_length=255)
    city: str = Field(min_length=1, max_length=120)
    region: str = Field(min_length=1, max_length=120)
    postal_code: str = Field(min_length=1, max_length=20)
    bed_count: int | None = Field(default=None, ge=0)
    latitude: Decimal | None = Field(default=None, ge=Decimal("-90"), le=Decimal("90"))
    longitude: Decimal | None = Field(default=None, ge=Decimal("-180"), le=Decimal("180"))


class HospitalProfileUpdate(HospitalProfileCreate):
    pass


class HospitalProfileResponse(BaseModel):
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
    bed_count: int | None
    latitude: Decimal | None =None
    longitude: Decimal | None = None
    is_verified: bool
    created_at: datetime
    updated_at: datetime


class HospitalDashboardStats(BaseModel):
    profile_complete: bool
    is_verified: bool
    member_since: datetime

    # Counts are calculated from persistent hospital-scoped records.
    total_waste_records: int = 0
    waste_tracking_available: bool = False
