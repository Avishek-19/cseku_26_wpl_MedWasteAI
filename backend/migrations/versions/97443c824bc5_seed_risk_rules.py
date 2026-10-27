"""seed risk rules

Revision ID: 97443c824bc5
Revises: 084208600e16
Create Date: 2026-08-17 10:35:38.899092

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '97443c824bc5'
down_revision: Union[str, Sequence[str], None] = '084208600e16'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# code -> (base_risk_level, quantity_escalation_threshold)
RULES = {
    "GENERAL": ("LOW", None),
    "INFECTIOUS": ("HIGH", 50),
    "SHARPS": ("HIGH", 20),
    "PHARMACEUTICAL": ("MEDIUM", 30),
    "CHEMICAL": ("HIGH", 20),
    "PATHOLOGICAL": ("CRITICAL", None),
    "RECYCLABLE": ("LOW", None),
    "OTHER_REGULATED": ("MEDIUM", 40),
}


def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind()
    categories = connection.execute(
        sa.text("SELECT id, code FROM waste_categories")
    ).fetchall()

    risk_rules = sa.table(
        "risk_rules",
        sa.column("id", sa.UUID()),
        sa.column("category_id", sa.UUID()),
        sa.column("base_risk_level", sa.String()),
        sa.column("quantity_escalation_threshold", sa.Numeric()),
        sa.column("is_active", sa.Boolean()),
    )

    rows = []
    for category_id, code in categories:
        if code not in RULES:
            continue
        base_risk_level, threshold = RULES[code]
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "category_id": str(category_id),
                "base_risk_level": base_risk_level,
                "quantity_escalation_threshold": threshold,
                "is_active": True,
            }
        )

    if rows:
        op.bulk_insert(risk_rules, rows)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM risk_rules")
