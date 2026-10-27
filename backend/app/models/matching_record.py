import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, JSON, Text, String, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.waste_enums import DestinationType


class MatchingRecord(Base):
    __tablename__ = "matching_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    waste_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("waste_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    destination_type: Mapped[DestinationType] = mapped_column(
        Enum(DestinationType, name="destination_type", native_enum=True), nullable=False
    )
    # Ranked list of up to 5 candidates: [{"id", "name", "city", "score",
    # "is_verified", "reasons": [...]}, ...], highest score first. The
    # first entry is the recommendation; the rest are alternatives.
    candidates: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    processing_method: Mapped[str | None] = mapped_column(String(80), nullable=True)
    routing_status: Mapped[str] = mapped_column(String(40), default="recommended", nullable=False)
    routing_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_method: Mapped[str] = mapped_column(String(40), default="deterministic_matching", nullable=False)
    match_score: Mapped[int | None] = mapped_column(Numeric(5, 2), nullable=True)
    requires_human_verification: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    confirmed_facility_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facility_profiles.id", ondelete="SET NULL"), nullable=True
    )
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
