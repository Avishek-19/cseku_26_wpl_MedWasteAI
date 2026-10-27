import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.waste_enums import RiskLevel

if TYPE_CHECKING:
    from app.models.waste_category import WasteCategory


class RiskRule(Base):
    """One row per waste category. Defines the base risk level the rule
    engine starts from, and an optional quantity threshold that escalates
    it by one tier. Seeded with sensible defaults now; edited by an admin
    in the Rule Management screen (Phase 14) — no schema change needed."""

    __tablename__ = "risk_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("waste_categories.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    base_risk_level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, name="risk_level", native_enum=True), nullable=False
    )
    # If the reported quantity exceeds this, escalate the risk level by one
    # tier (capped at CRITICAL). Null means no quantity-based escalation.
    quantity_escalation_threshold: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

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
