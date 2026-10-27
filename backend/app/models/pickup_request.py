import uuid
import secrets
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Text, UniqueConstraint, func, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.waste_enums import PickupPriority, PickupStatus

if TYPE_CHECKING:
    from app.models.vehicle import Vehicle
    from app.models.waste_record import WasteRecord


class PickupRequest(Base):
    __tablename__ = "pickup_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    hospital_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hospital_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    priority: Mapped[PickupPriority] = mapped_column(
        Enum(PickupPriority, name="pickup_priority", native_enum=True), nullable=False
    )
    status: Mapped[PickupStatus] = mapped_column(
        Enum(PickupStatus, name="pickup_status", native_enum=True),
        nullable=False,
        default=PickupStatus.REQUESTED,
        index=True,
    )

    requested_pickup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    requested_pickup_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    assigned_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )
    assigned_collector_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    handover_token: Mapped[str] = mapped_column(String(128), default=lambda: secrets.token_urlsafe(32), unique=True, nullable=False)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    assigned_vehicle: Mapped["Vehicle | None"] = relationship(lazy="joined")
    items: Mapped[list["PickupRequestItem"]] = relationship(
        back_populates="pickup_request", cascade="all, delete-orphan"
    )


class PickupRequestItem(Base):
    __tablename__ = "pickup_request_items"
    __table_args__ = (UniqueConstraint("pickup_request_id", "waste_record_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pickup_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pickup_requests.id", ondelete="CASCADE"), nullable=False
    )
    waste_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("waste_records.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    pickup_request: Mapped["PickupRequest"] = relationship(back_populates="items")
    waste_record: Mapped["WasteRecord"] = relationship(lazy="joined")
