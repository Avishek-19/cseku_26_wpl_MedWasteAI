"""merge_multiple_heads

Revision ID: 044c38e7ef3f
Revises: 3d7f1a9b4c21, a4d8e1f9c203
Create Date: 2026-09-25 13:42:24.653322

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '044c38e7ef3f'
down_revision: Union[str, Sequence[str], None] = ('3d7f1a9b4c21', 'a4d8e1f9c203')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
