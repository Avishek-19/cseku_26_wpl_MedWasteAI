import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class TrackingSessionStatus(str, enum.Enum):
    CREATED = "created"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    OFFLINE = "offline"


class LocationSource(str, enum.Enum):
    SIMULATOR = "simulator"
    GPS_DEVICE = "gps_device"
    MOBILE_APP = "mobile_app"
    MANUAL = "manual"


class GPSAnomalyType(str, enum.Enum):
    INVALID_COORDINATES = "invalid_coordinates"
    IMPOSSIBLE_SPEED = "impossible_speed"
    LARGE_JUMP = "large_jump"
    STALE_TIMESTAMP = "stale_timestamp"


class TrackingSession(Base):
    __tablename__ = "tracking_sessions"
    # Hard guarantee even if two workers race or route-start bypasses the API.
    __table_args__ = (
        Index("uq_tracking_vehicle_open_session", "vehicle_id", unique=True,
              postgresql_where=text("status IN ('CREATED', 'ACTIVE', 'PAUSED')"),
              sqlite_where=text("status IN ('CREATED', 'ACTIVE', 'PAUSED')")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pickup_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pickup_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    current_route_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("routes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[TrackingSessionStatus] = mapped_column(
        Enum(TrackingSessionStatus, name="tracking_session_status", native_enum=True),
        nullable=False,
        default=TrackingSessionStatus.CREATED,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_location_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TrackingLocation(Base):
    __tablename__ = "tracking_locations"
    __table_args__ = (
        Index("ix_tracking_locations_session_timestamp", "tracking_session_id", "timestamp"),
        Index("ix_tracking_locations_vehicle_timestamp", "vehicle_id", "timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tracking_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracking_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    speed_kmh: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    heading_degrees: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    altitude_m: Mapped[Decimal | None] = mapped_column(Numeric(9, 2), nullable=True)
    provenance_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    source: Mapped[LocationSource] = mapped_column(
        Enum(LocationSource, name="location_source", native_enum=True), nullable=False
    )
    anomaly_type: Mapped[GPSAnomalyType | None] = mapped_column(
        Enum(GPSAnomalyType, name="gps_anomaly_type", native_enum=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GPSDeviceNonce(Base):
    """Durable, unique anti-replay claim, shared by all workers via PostgreSQL."""
    __tablename__ = "gps_device_nonces"
    __table_args__ = (UniqueConstraint("device_id", "nonce", name="uq_gps_device_nonce"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    nonce: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tracking_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tracking_sessions.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
