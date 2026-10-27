"""add_proof_submitted_to_waste_status

Revision ID: 577b477b9526
Revises: 044c38e7ef3f
Create Date: 2026-09-25 18:46:48.924078

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '577b477b9526'
down_revision: Union[str, Sequence[str], None] = '044c38e7ef3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TYPE waste_status ADD VALUE IF NOT EXISTS 'PROOF_SUBMITTED'"))


def downgrade() -> None:
    pass