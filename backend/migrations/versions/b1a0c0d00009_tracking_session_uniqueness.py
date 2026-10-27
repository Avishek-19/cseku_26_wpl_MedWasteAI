"""Issue 22: at most one open tracking session per vehicle, across workers.

Deployment requirement: resolve pre-existing duplicate CREATED/ACTIVE/PAUSED
sessions first; index creation intentionally fails instead of silently deleting
or cancelling historical session records.
"""
from alembic import op
import sqlalchemy as sa

revision = "b1a0c0d00009"
down_revision = "b1a0c0d00008"
branch_labels = None
depends_on = None


def upgrade():
    # Do not silently delete conflicting sessions: their status is part of an
    # auditable route/vehicle history. Give operators the affected vehicle ID.
    duplicates = op.get_bind().execute(sa.text("""
        SELECT vehicle_id, COUNT(*) AS n FROM tracking_sessions
        WHERE status IN ('CREATED', 'ACTIVE', 'PAUSED')
        GROUP BY vehicle_id HAVING COUNT(*) > 1
        LIMIT 10
    """)).all()
    if duplicates:
        raise RuntimeError('Resolve duplicate open tracking sessions before migration: ' +
                           ', '.join(str(row[0]) for row in duplicates))
    op.create_index("uq_tracking_vehicle_open_session", "tracking_sessions", ["vehicle_id"],
        unique=True, postgresql_where=sa.text("status IN ('CREATED', 'ACTIVE', 'PAUSED')"),
        sqlite_where=sa.text("status IN ('CREATED', 'ACTIVE', 'PAUSED')"))
    op.create_table('invoice_adjustments',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('invoice_id', sa.UUID(), sa.ForeignKey('hospital_invoices.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('waste_record_id', sa.UUID(), sa.ForeignKey('waste_records.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('measured_kg', sa.Numeric(12,3), nullable=False),
        sa.Column('collection_bdt', sa.Numeric(14,2), nullable=False),
        sa.Column('treatment_bdt', sa.Numeric(14,2), nullable=False),
        sa.Column('platform_bdt', sa.Numeric(14,2), nullable=False),
        sa.Column('total_bdt', sa.Numeric(14,2), nullable=False),
        sa.Column('reason', sa.String(160), nullable=False),
        sa.Column('actor_user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('waste_record_id', name='uq_invoice_adjustment_batch'))
    op.create_index('ix_invoice_adjustments_invoice_id', 'invoice_adjustments', ['invoice_id'])


def downgrade():
    op.drop_index('ix_invoice_adjustments_invoice_id', table_name='invoice_adjustments')
    op.drop_table('invoice_adjustments')
    op.drop_index("uq_tracking_vehicle_open_session", table_name="tracking_sessions")
