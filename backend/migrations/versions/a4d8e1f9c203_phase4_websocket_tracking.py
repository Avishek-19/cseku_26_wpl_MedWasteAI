"""phase 4 websocket real-time tracking

Revision ID: a4d8e1f9c203
Revises: 9b2f6e4c8a10
"""
from alembic import op
import sqlalchemy as sa

revision = "a4d8e1f9c203"
down_revision = "9b2f6e4c8a10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tracking_sessions", sa.Column("current_route_id", sa.UUID(), nullable=True))
    op.create_index("ix_tracking_sessions_current_route_id", "tracking_sessions", ["current_route_id"], unique=False)
    op.create_foreign_key(
        "fk_tracking_sessions_current_route_id_routes",
        "tracking_sessions", "routes", ["current_route_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_tracking_sessions_current_route_id_routes", "tracking_sessions", type_="foreignkey")
    op.drop_index("ix_tracking_sessions_current_route_id", table_name="tracking_sessions")
    op.drop_column("tracking_sessions", "current_route_id")
