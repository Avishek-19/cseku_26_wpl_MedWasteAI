"""unify processing facility workflow

Revision ID: fd45a1c2b789
Revises: ab12cd34ef56
"""
from alembic import op
import sqlalchemy as sa

revision = "fd45a1c2b789"
down_revision = "ab12cd34ef56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TYPE destination_type ADD VALUE IF NOT EXISTS 'WASTE_PROCESSING_FACILITY'"))
    # Extend the existing PostgreSQL enum used by the chain-of-custody log.
    for value in ("PROCESSING", "PROOF_SUBMITTED", "VERIFIED", "COMPLETED"):
        op.execute(sa.text(f"ALTER TYPE waste_event_type ADD VALUE IF NOT EXISTS '{value}'"))
    op.add_column("facility_profiles", sa.Column("processing_services", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("facility_profiles", sa.Column("availability_status", sa.String(length=24), nullable=False, server_default="available"))
    op.add_column("facility_profiles", sa.Column("facility_type", sa.String(length=80), nullable=False, server_default="Waste Processing Facility"))
    op.add_column("matching_records", sa.Column("processing_method", sa.String(length=80), nullable=True))
    op.add_column("matching_records", sa.Column("routing_status", sa.String(length=40), nullable=False, server_default="recommended"))
    op.add_column("matching_records", sa.Column("routing_reason", sa.Text(), nullable=True))
    op.add_column("matching_records", sa.Column("decision_method", sa.String(length=40), nullable=False, server_default="deterministic_matching"))
    op.add_column("matching_records", sa.Column("match_score", sa.Numeric(5, 2), nullable=True))
    op.add_column("matching_records", sa.Column("requires_human_verification", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table(
        "processing_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("waste_record_id", sa.UUID(), nullable=False),
        sa.Column("facility_id", sa.UUID(), nullable=False),
        sa.Column("processing_method", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="received"),
        sa.Column("proof_note", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proof_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["waste_record_id"], ["waste_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["facility_id"], ["facility_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("waste_record_id"),
    )
    op.create_index("ix_processing_records_waste_record_id", "processing_records", ["waste_record_id"])
    op.create_index("ix_processing_records_facility_id", "processing_records", ["facility_id"])


def downgrade() -> None:
    # PostgreSQL enum values are intentionally not removed during downgrade.
    op.drop_index("ix_processing_records_facility_id", table_name="processing_records")
    op.drop_index("ix_processing_records_waste_record_id", table_name="processing_records")
    op.drop_table("processing_records")
    op.drop_column("matching_records", "requires_human_verification")
    op.drop_column("matching_records", "match_score")
    op.drop_column("matching_records", "decision_method")
    op.drop_column("matching_records", "routing_reason")
    op.drop_column("matching_records", "routing_status")
    op.drop_column("matching_records", "processing_method")
    op.drop_column("facility_profiles", "facility_type")
    op.drop_column("facility_profiles", "availability_status")
    op.drop_column("facility_profiles", "processing_services")
