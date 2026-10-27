import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.route import RouteStatus, RouteStopStatus


class RouteStopCreate(BaseModel):
    pickup_id: uuid.UUID
    sequence: int = Field(ge=1)
    latitude: Decimal = Field(ge=Decimal("-90"), le=Decimal("90"))
    longitude: Decimal = Field(ge=Decimal("-180"), le=Decimal("180"))


class RouteOptimizeStop(BaseModel):
    pickup_id: uuid.UUID
    latitude: Decimal = Field(ge=Decimal("-90"), le=Decimal("90"))
    longitude: Decimal = Field(ge=Decimal("-180"), le=Decimal("180"))


class RouteOptimizeRequest(BaseModel):
    vehicle_id: uuid.UUID
    pickup_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    origin_latitude: Decimal | None = Field(default=None, ge=Decimal("-90"), le=Decimal("90"))
    origin_longitude: Decimal | None = Field(default=None, ge=Decimal("-180"), le=Decimal("180"))
    # Explicit coordinates are useful during rollout when legacy hospital/facility
    # records have not yet been geocoded.
    stop_coordinates: list[RouteOptimizeStop] = Field(default_factory=list, max_length=50)
    destination_latitude: Decimal | None = Field(default=None, ge=Decimal("-90"), le=Decimal("90"))
    destination_longitude: Decimal | None = Field(default=None, ge=Decimal("-180"), le=Decimal("180"))
    start_at: datetime | None = None
    change_reason: str | None = Field(default=None, max_length=500)


class RouteCreate(BaseModel):
    vehicle_id: uuid.UUID
    tracking_session_id: uuid.UUID | None = None
    stops: list[RouteStopCreate] = Field(default_factory=list)
    origin_latitude: Decimal | None = Field(default=None, ge=Decimal("-90"), le=Decimal("90"))
    origin_longitude: Decimal | None = Field(default=None, ge=Decimal("-180"), le=Decimal("180"))
    destination_latitude: Decimal | None = Field(default=None, ge=Decimal("-90"), le=Decimal("90"))
    destination_longitude: Decimal | None = Field(default=None, ge=Decimal("-180"), le=Decimal("180"))


class RouteStopResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    route_id: uuid.UUID
    pickup_id: uuid.UUID
    sequence: int
    latitude: Decimal
    longitude: Decimal
    status: RouteStopStatus
    estimated_arrival_at: datetime | None
    arrived_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class RouteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vehicle_id: uuid.UUID
    tracking_session_id: uuid.UUID | None
    version: int
    status: RouteStatus
    destination_state: str
    destination_arrived_at: datetime | None
    destination_received_at: datetime | None
    completed_at: datetime | None
    is_optimized: bool
    total_distance_km: Decimal | None
    estimated_duration_minutes: int | None
    origin_latitude: Decimal | None
    origin_longitude: Decimal | None
    destination_latitude: Decimal | None
    destination_longitude: Decimal | None
    change_reason: str | None
    routing_provider: str | None
    geometry: dict | None
    optimization_details: dict | None
    created_at: datetime
    updated_at: datetime
    stops: list[RouteStopResponse] = Field(default_factory=list)
