"""Issue 14/15: durable dead-letter audit fields and traceable recycling sale lots."""
from alembic import op
import sqlalchemy as sa

revision = 'b1a0c0d00008'
down_revision = 'b1a0c0d00007'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('event_outbox', sa.Column('last_error', sa.String(320), nullable=True))
    op.add_column('event_outbox', sa.Column('last_failed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('event_outbox', sa.Column('dead_lettered_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_event_outbox_dead_lettered_at','event_outbox',['dead_lettered_at'])
    # Previously exhausted events were silently stranded. Surface them for recovery.
    op.execute("""UPDATE event_outbox SET topic = 'waste.report.dead_letter',
        last_error = 'Legacy attempts exhausted; original failure details unavailable',
        last_failed_at = CURRENT_TIMESTAMP,
        dead_lettered_at = CURRENT_TIMESTAMP,
        lease_owner = NULL, lease_expires_at = NULL
        WHERE topic = 'waste.report.progress' AND delivered_at IS NULL AND attempts >= 5""")
    op.create_table('recycling_sale_lots',
        sa.Column('id',sa.UUID(),primary_key=True),
        sa.Column('sale_id',sa.UUID(),sa.ForeignKey('recycling_sales.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('waste_record_id',sa.UUID(),sa.ForeignKey('waste_records.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('hospital_org_id',sa.UUID(),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('contribution_kg',sa.Numeric(12,3),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint('waste_record_id',name='uq_recycling_sale_lot_waste_record'),
        sa.CheckConstraint('contribution_kg > 0',name='ck_recycling_lot_positive_kg'))
    op.create_index('ix_recycling_sale_lots_sale_id','recycling_sale_lots',['sale_id'])
    op.create_index('ix_recycling_sale_lots_hospital_org_id','recycling_sale_lots',['hospital_org_id'])


def downgrade():
    op.drop_index('ix_recycling_sale_lots_hospital_org_id',table_name='recycling_sale_lots')
    op.drop_index('ix_recycling_sale_lots_sale_id',table_name='recycling_sale_lots')
    op.drop_table('recycling_sale_lots')
    op.drop_index('ix_event_outbox_dead_lettered_at',table_name='event_outbox')
    op.drop_column('event_outbox','dead_lettered_at')
    op.drop_column('event_outbox','last_failed_at')
    op.drop_column('event_outbox','last_error')
