"""Non-destructive pickup end-window support.

Revision ID: b1a0c0d00004
Revises: b1a0c0d00003
"""
from alembic import op
import sqlalchemy as sa
revision = "b1a0c0d00004"
down_revision = "b1a0c0d00003"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("pickup_requests", sa.Column("requested_pickup_end_at", sa.DateTime(timezone=True), nullable=True))

def downgrade():
    op.drop_column("pickup_requests", "requested_pickup_end_at")
