"""add_completed_to_pickup_status

Revision ID: 1ac14bb0cc6a
Revises: 577b477b9526
Create Date: 2026-09-25 19:02:57.676811

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1ac14bb0cc6a'
down_revision: Union[str, Sequence[str], None] = '577b477b9526'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TYPE pickup_status ADD VALUE IF NOT EXISTS 'COMPLETED'"))


def downgrade() -> None:
    
    pass
