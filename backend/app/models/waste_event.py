import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.waste_enums import WasteEventType, WasteStatus

if TYPE_CHECKING:
    from app.models.user import User


class WasteEvent(Base):
    __tablename__ = "waste_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    waste_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("waste_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    event_type: Mapped[WasteEventType] = mapped_column(
        Enum(WasteEventType, name="waste_event_type", native_enum=True), nullable=False
    )
    # The record's status as of this event — a literal, immutable record of
    # each status transition, independent of whatever the record shows now.
    status_snapshot: Mapped[WasteStatus] = mapped_column(
        Enum(WasteStatus, name="waste_status", native_enum=True, create_type=False), nullable=False
    )

    # Who performed the action. Null for automatic system steps (e.g. the
    # deterministic auto-assignment algorithm picking a vehicle) rather
    # than a specific person's direct action.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Snapshot of the batch quantity at event time (spec: "quantity tracking").
    quantity: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Structured extra detail specific to the event type, e.g. matched
    # destination name/score, assigned vehicle code, confidence level.
    event_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    actor: Mapped["User | None"] = relationship(lazy="joined")
