import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, Sequence, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.waste_enums import WasteStatus, WasteUnit

if TYPE_CHECKING:
    from app.models.waste_attachment import WasteAttachment
    from app.models.waste_category import WasteCategory

# Backs waste_code generation (MW-{year}-{sequence:06d}). Attached to
# Base.metadata so it's created by both Alembic and the test suite's
# metadata.create_all(), and stays in sync between the two.
waste_record_seq = Sequence("waste_record_seq", metadata=Base.metadata)


class WasteRecord(Base):
    __tablename__ = "waste_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Human-readable tracking ID, e.g. MW-2026-000001 (spec section 10)
    waste_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)

    hospital_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hospital_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("waste_categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reported_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    quantity: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    unit: Mapped[WasteUnit] = mapped_column(
        Enum(WasteUnit, name="waste_unit", native_enum=True), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # When the waste was actually generated at the hospital (may predate the report)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[WasteStatus] = mapped_column(
        Enum(WasteStatus, name="waste_status", native_enum=True),
        nullable=False,
        default=WasteStatus.REPORTED,
        index=True,
    )

    # Captured when the Waste Processing Facility confirms receipt
    # (Phase 11) — compared against `quantity` for weight discrepancy
    # detection. Null until receipt is confirmed.
    received_quantity: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    received_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    category: Mapped["WasteCategory"] = relationship(lazy="joined")
    attachments: Mapped[list["WasteAttachment"]] = relationship(
        back_populates="waste_record", cascade="all, delete-orphan"
    )
