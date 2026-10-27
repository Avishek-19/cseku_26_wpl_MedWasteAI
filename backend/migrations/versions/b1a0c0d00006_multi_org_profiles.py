"""Allow one owner to maintain separate profiles for different companies.

Revision ID: b1a0c0d00006
Revises: b1a0c0d00005
Before migration, ensure every linked profile has one distinct organization.
"""
from alembic import op

revision = 'b1a0c0d00006'
down_revision = 'b1a0c0d00005'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('hospital_profiles', 'facility_profiles'):
        # Fail if legacy ownership is ambiguous. Existing unlinked rows remain
        # accessible only by original user until explicitly linked.
        op.drop_index(f'ix_{table}_user_id', table_name=table)
        op.create_index(f'ix_{table}_user_id', table, ['user_id'], unique=False)
        op.create_index(f'uq_{table}_organization', table, ['organization_id'], unique=True)


def downgrade():
    for table in ('facility_profiles', 'hospital_profiles'):
        op.drop_index(f'uq_{table}_organization', table_name=table)
        op.drop_index(f'ix_{table}_user_id', table_name=table)
        # Downgrade is refused by PostgreSQL if a user owns multiple profiles.
        op.create_index(f'ix_{table}_user_id', table, ['user_id'], unique=True)
