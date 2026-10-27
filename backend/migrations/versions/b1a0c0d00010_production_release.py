"""Unclassified reporting, session revocation and receipt review evidence.

Revision ID: b1a0c0d00010
Revises: b1a0c0d00009
"""
from alembic import op
import sqlalchemy as sa

revision = "b1a0c0d00010"
down_revision = "b1a0c0d00009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payment_intents", sa.Column("last_checked_at", sa.DateTime(timezone=True)))
    op.add_column("payment_intents", sa.Column("reconciliation_attempts", sa.Integer(), server_default="0", nullable=False))
    op.create_index("ix_payment_reconciliation", "payment_intents", ["state", "last_checked_at"])
    op.add_column("users", sa.Column("auth_version", sa.Integer(), server_default="0", nullable=False))
    op.execute("""INSERT INTO waste_categories
        (id, code, name, description, is_recyclable, is_active)
        VALUES ('ba8dfb65-f10b-4e9e-bfa7-c616982fd212', 'PENDING',
        'Pending classification', 'Reported batch awaiting a confirmed classification.', false, true)
        ON CONFLICT (code) DO NOTHING""")
    op.create_table("recycling_receipt_reviews",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("sale_id", sa.UUID(), sa.ForeignKey("recycling_sales.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("bank_reference", sa.String(120), nullable=False, unique=True),
        sa.Column("received_bdt", sa.Numeric(14, 2), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("evidence_note", sa.Text(), nullable=False),
        sa.Column("submitted_by", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by", sa.UUID(), sa.ForeignKey("users.id")),
        sa.Column("state", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("received_bdt > 0", name="ck_receipt_positive"))


def downgrade():
    op.drop_table("recycling_receipt_reviews")
    op.drop_index("ix_payment_reconciliation", table_name="payment_intents")
    op.drop_column("payment_intents", "reconciliation_attempts")
    op.drop_column("payment_intents", "last_checked_at")
    op.drop_column("users", "auth_version")
    # PENDING reference data may already be referenced by reported batches.
