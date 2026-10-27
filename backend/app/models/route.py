import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RouteStatus(str, enum.Enum):
    DRAFT = "draft"
    READY = "ready"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RouteStopStatus(str, enum.Enum):
    PENDING = "pending"
    EN_ROUTE = "en_route"
    ARRIVED = "arrived"
    COLLECTED = "collected"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class RouteDestinationState(str, enum.Enum):
    COLLECTION = "collection"
    EN_ROUTE_TO_DESTINATION = "en_route_to_destination"
    AT_DESTINATION = "at_destination"
    RECEIVED = "received"
    COMPLETED = "completed"


class Route(Base):
    __tablename__ = "routes"
    __table_args__ = (Index("ix_routes_vehicle_status", "vehicle_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tracking_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracking_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[RouteStatus] = mapped_column(
        Enum(RouteStatus, name="route_status", native_enum=True), nullable=False, default=RouteStatus.DRAFT, index=True
    )
    destination_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=RouteDestinationState.COLLECTION.value, index=True
    )
    destination_arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    destination_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_optimized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    total_distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin_latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    origin_longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    destination_latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    destination_longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    routing_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Provider-returned GeoJSON LineString when available; empty when using
    # distance-only fallback.
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    optimization_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RouteStop(Base):
    __tablename__ = "route_stops"
    __table_args__ = (
        UniqueConstraint("route_id", "sequence", name="uq_route_stops_route_sequence"),
        UniqueConstraint("route_id", "pickup_id", name="uq_route_stops_route_pickup"),
        Index("ix_route_stops_route_status", "route_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pickup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pickup_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    status: Mapped[RouteStopStatus] = mapped_column(
        Enum(RouteStopStatus, name="route_stop_status", native_enum=True), nullable=False, default=RouteStopStatus.PENDING
    )
    estimated_arrival_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
