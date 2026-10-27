"""add explicit transport destination lifecycle to routes

Revision ID: 3d7f1a9b4c21
Revises: ef78a9b1c234
Create Date: 2026-09-25 11:55:00
"""
from alembic import op
import sqlalchemy as sa

revision = "3d7f1a9b4c21"
down_revision = "ef78a9b1c234"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("routes", sa.Column("destination_state", sa.String(length=32), nullable=False, server_default="collection"))
    op.add_column("routes", sa.Column("destination_arrived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("routes", sa.Column("destination_received_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("routes", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_routes_destination_state", "routes", ["destination_state"], unique=False)

def downgrade() -> None:
    op.drop_index("ix_routes_destination_state", table_name="routes")
    op.drop_column("routes", "completed_at")
    op.drop_column("routes", "destination_received_at")
    op.drop_column("routes", "destination_arrived_at")
    op.drop_column("routes", "destination_state")
