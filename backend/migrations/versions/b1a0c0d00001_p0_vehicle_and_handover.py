"""P0: reserve before departure and require durable handover proof."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "b1a0c0d00001"
down_revision = "1ac14bb0cc6a"
branch_labels = None
depends_on = None

def upgrade():
    # PostgreSQL enum labels are SQLAlchemy member NAMES (not lower-case values).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE vehicle_status ADD VALUE IF NOT EXISTS 'RESERVED'")
    op.add_column('pickup_requests', sa.Column('handover_token', sa.String(128), nullable=True))
    op.execute("UPDATE pickup_requests SET handover_token = replace(gen_random_uuid()::text,'-','') || replace(gen_random_uuid()::text,'-','') WHERE handover_token IS NULL")
    op.alter_column('pickup_requests', 'handover_token', nullable=False)
    op.create_unique_constraint('uq_pickup_handover_token', 'pickup_requests', ['handover_token'])
    op.create_table('collection_proofs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('pickup_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('pickup_requests.id'), nullable=False, unique=True),
        sa.Column('verified_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('accepted_weight_kg', sa.Numeric(12,3), nullable=False),
        sa.Column('packaging_condition', sa.String(40), nullable=False),
        sa.Column('acknowledgement', sa.String(24), nullable=False),
        sa.Column('exception_reason', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.create_index('ix_collection_proofs_pickup_id', 'collection_proofs', ['pickup_id'])
    # Existing ON_ROUTE assignments without an active tracking route were created
    # on reservation; correct only those rows. Do not touch actual active trips.
    op.execute("""UPDATE vehicles v SET status = 'RESERVED' WHERE v.status = 'ON_ROUTE'
       AND EXISTS (SELECT 1 FROM pickup_requests p WHERE p.assigned_vehicle_id = v.id AND p.status = 'ASSIGNED')
       AND NOT EXISTS (SELECT 1 FROM routes r WHERE r.vehicle_id = v.id AND r.status = 'ACTIVE')""")

def downgrade():
    op.drop_index('ix_collection_proofs_pickup_id', 'collection_proofs')
    op.drop_table('collection_proofs')
    op.drop_constraint('uq_pickup_handover_token','pickup_requests', type_='unique')
    op.drop_column('pickup_requests','handover_token')
    op.execute("UPDATE vehicles SET status = 'AVAILABLE' WHERE status = 'RESERVED'")
    # PostgreSQL does not support dropping enum labels; retain unused RESERVED.
