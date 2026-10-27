import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.tracking import GPSAnomalyType, LocationSource, TrackingSessionStatus


class TrackingSessionCreate(BaseModel):
    vehicle_id: uuid.UUID
    pickup_id: uuid.UUID | None = None


class TrackingSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vehicle_id: uuid.UUID
    pickup_id: uuid.UUID | None
    current_route_id: uuid.UUID | None
    status: TrackingSessionStatus
    started_at: datetime | None
    ended_at: datetime | None
    last_location_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GPSLocationCreate(BaseModel):
    latitude: Decimal = Field(ge=Decimal("-90"), le=Decimal("90"))
    longitude: Decimal = Field(ge=Decimal("-180"), le=Decimal("180"))
    timestamp: datetime
    speed_kmh: Decimal | None = Field(default=None, ge=0)
    heading_degrees: Decimal | None = Field(default=None, ge=0, lt=360)
    accuracy_m: Decimal | None = Field(default=None, ge=0)
    altitude_m: Decimal | None = None
    source: LocationSource = LocationSource.MANUAL

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include timezone information")
        return value


class TrackingLocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tracking_session_id: uuid.UUID
    vehicle_id: uuid.UUID
    latitude: Decimal
    longitude: Decimal
    timestamp: datetime
    speed_kmh: Decimal | None
    heading_degrees: Decimal | None
    accuracy_m: Decimal | None
    altitude_m: Decimal | None
    source: LocationSource
    provenance_verified: bool
    anomaly_type: GPSAnomalyType | None
    created_at: datetime
