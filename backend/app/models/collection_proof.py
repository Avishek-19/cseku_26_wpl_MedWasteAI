"""Persisted, single-use handover evidence; no patient-identifiable material."""
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

class CollectionProof(Base):
    __tablename__ = "collection_proofs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pickup_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pickup_requests.id"), nullable=False, unique=True, index=True)
    verified_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    accepted_weight_kg: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    packaging_condition: Mapped[str] = mapped_column(String(40), nullable=False)
    acknowledgement: Mapped[str] = mapped_column(String(24), nullable=False)
    exception_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
