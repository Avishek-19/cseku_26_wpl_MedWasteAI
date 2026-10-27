"""Issue 12: provenance auditing and replay protection for GPS."""
from alembic import op
import sqlalchemy as sa

revision = "b1a0c0d00007"
down_revision = "b1a0c0d00006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tracking_locations', sa.Column('provenance_verified', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('gps_device_nonces',
        sa.Column('id', sa.UUID(), primary_key=True, nullable=False),
        sa.Column('device_id', sa.UUID(), nullable=False),
        sa.Column('nonce', sa.UUID(), nullable=False),
        sa.Column('tracking_session_id', sa.UUID(), sa.ForeignKey('tracking_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('device_id', 'nonce', name='uq_gps_device_nonce'))
    op.create_index('ix_gps_device_nonces_device_id', 'gps_device_nonces', ['device_id'])


def downgrade():
    op.drop_index('ix_gps_device_nonces_device_id', table_name='gps_device_nonces')
    op.drop_table('gps_device_nonces')
    op.drop_column('tracking_locations', 'provenance_verified')
