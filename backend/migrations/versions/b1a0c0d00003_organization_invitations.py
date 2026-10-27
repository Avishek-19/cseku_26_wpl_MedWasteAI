"""Add organization_invitations for member onboarding.

Revision ID: b1a0c0d00003
Revises: b1a0c0d00002
Create Date: 2026-10-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b1a0c0d00003"
down_revision: Union[str, Sequence[str], None] = "b1a0c0d00002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organization_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("member_role", sa.String(20), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("organization_id", "email", name="uq_org_invite_email"),
    )
    op.create_index("ix_org_invitations_token", "organization_invitations", ["token"], unique=True)
    op.create_index("ix_organization_invitations_organization_id", "organization_invitations", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_organization_invitations_organization_id", table_name="organization_invitations")
    op.drop_index("ix_org_invitations_token", table_name="organization_invitations")
    op.drop_table("organization_invitations")
