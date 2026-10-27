import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.waste_enums import VehicleStatus


class VehicleCreate(BaseModel):
    vehicle_code: str = Field(min_length=1, max_length=40)
    capacity_kg: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    location: str | None = Field(default=None, max_length=255)
    organization_id: uuid.UUID | None = None
    assigned_collector_id: uuid.UUID | None = None


class VehicleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    assigned_collector_id: uuid.UUID | None = None


class VehicleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vehicle_code: str
    assigned_collector_id: uuid.UUID
    organization_id: uuid.UUID | None
    capacity_kg: Decimal
    status: VehicleStatus
    location: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
