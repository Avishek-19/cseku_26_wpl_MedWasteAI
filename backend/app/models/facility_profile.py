import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class TreatmentFacilityProfile(Base):
    __tablename__ = "facility_profiles"
    __table_args__ = (Index("uq_facility_profiles_organization", "organization_id", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Explicit organizational ownership; nullable for legacy profiles until backfill.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    registration_number: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_person: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)

    address_line: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    region: Mapped[str] = mapped_column(String(120), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    # Optional WGS84 coordinates used by route optimization. Existing
    # addresses remain valid when coordinates are not yet geocoded.
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)

    capacity_kg: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    # Running total of waste currently committed to this facility. Updated
    # by the matching/processing workflow in later phases; starts at 0.
    current_utilization_kg: Mapped[float] = mapped_column(
        Numeric(10, 2), default=0, nullable=False
    )

    # Set by an administrator in the Admin Panel (Phase 14).
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Database-driven capabilities for the unified Waste Processing Facility.
    # Examples: AUTOCLOVE, INCINERATION, RECYCLING, MATERIAL_RECOVERY, FINAL_DISPOSAL.
    processing_services: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Free-form authorized services for capabilities not covered by the standard list.
    other_services: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    availability_status: Mapped[str] = mapped_column(String(24), default="available", nullable=False)
    facility_type: Mapped[str] = mapped_column(String(80), default="Waste Processing Facility", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @property
    def available_capacity_kg(self):
        return max(0, float(self.capacity_kg) - float(self.current_utilization_kg))
