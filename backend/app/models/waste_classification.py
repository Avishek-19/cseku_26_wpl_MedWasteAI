import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.waste_enums import ClassificationConfidence, ClassificationSource

if TYPE_CHECKING:
    from app.models.waste_category import WasteCategory


class WasteClassification(Base):
    __tablename__ = "waste_classifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    waste_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("waste_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    suggested_category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("waste_categories.id", ondelete="RESTRICT"), nullable=False
    )

    source: Mapped[ClassificationSource] = mapped_column(
        Enum(ClassificationSource, name="classification_source", native_enum=True),
        nullable=False,
    )
    confidence: Mapped[ClassificationConfidence] = mapped_column(
        Enum(ClassificationConfidence, name="classification_confidence", native_enum=True),
        nullable=False,
    )
    # List of {"category_code": str, "matched_keywords": [str, ...]} — kept
    # as plain JSON so the reasoning is transparent and inspectable.
    matched_rules: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)

    # Manual correction notes (source == MANUAL only)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    suggested_category: Mapped["WasteCategory"] = relationship(lazy="joined")
