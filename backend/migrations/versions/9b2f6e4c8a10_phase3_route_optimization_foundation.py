"""phase 3 route optimization foundation

Revision ID: 9b2f6e4c8a10
Revises: 7a91c4d2e6f0
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "9b2f6e4c8a10"
down_revision = "7a91c4d2e6f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hospital_profiles", sa.Column("latitude", sa.Numeric(9, 6), nullable=True))
    op.add_column("hospital_profiles", sa.Column("longitude", sa.Numeric(9, 6), nullable=True))
    op.add_column("facility_profiles", sa.Column("latitude", sa.Numeric(9, 6), nullable=True))
    op.add_column("facility_profiles", sa.Column("longitude", sa.Numeric(9, 6), nullable=True))

    op.add_column("routes", sa.Column("routing_provider", sa.String(length=40), nullable=True))
    op.add_column("routes", sa.Column("geometry", sa.JSON(), nullable=True))
    op.add_column("routes", sa.Column("optimization_details", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("routes", "optimization_details")
    op.drop_column("routes", "geometry")
    op.drop_column("routes", "routing_provider")
    op.drop_column("facility_profiles", "longitude")
    op.drop_column("facility_profiles", "latitude")
    op.drop_column("hospital_profiles", "longitude")
    op.drop_column("hospital_profiles", "latitude")
