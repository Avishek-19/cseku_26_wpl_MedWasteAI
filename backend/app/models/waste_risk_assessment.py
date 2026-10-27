import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, JSON, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.waste_enums import AssessmentSource, RiskLevel, SuggestedHandling


class WasteRiskAssessment(Base):
    __tablename__ = "waste_risk_assessments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    waste_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("waste_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    risk_level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, name="risk_level", native_enum=True, create_type=False), nullable=False
    )
    recyclability_decision: Mapped[bool] = mapped_column(Boolean, nullable=False)
    suggested_handling: Mapped[SuggestedHandling] = mapped_column(
        Enum(SuggestedHandling, name="suggested_handling", native_enum=True), nullable=False
    )

    source: Mapped[AssessmentSource] = mapped_column(
        Enum(AssessmentSource, name="assessment_source", native_enum=True), nullable=False
    )
    # {"base_risk_level": str, "quantity_escalated": bool, "category_recyclable": bool}
    factors: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
