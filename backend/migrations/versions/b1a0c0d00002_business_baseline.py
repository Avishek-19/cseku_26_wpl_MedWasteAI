"""Additive company tenancy, contracts, immutable billing and payment objects.

Fixed schema snapshot: this migration does not import application models.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "b1a0c0d00002"
down_revision = "b1a0c0d00001"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('organizations',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('org_type', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('owner_user_id', postgresql.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_organizations_status', 'organizations', ['status'], unique=False)
    op.create_index('ix_organizations_owner_user_id', 'organizations', ['owner_user_id'], unique=False)
    op.create_index('ix_organizations_org_type', 'organizations', ['org_type'], unique=False)
    op.create_table('organization_members',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('organization_id', postgresql.UUID(), nullable=False),
        sa.Column('user_id', postgresql.UUID(), nullable=False),
        sa.Column('member_role', sa.String(length=20), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('organization_id','user_id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_organization_members_user_id', 'organization_members', ['user_id'], unique=False)
    op.create_index('ix_organization_members_organization_id', 'organization_members', ['organization_id'], unique=False)
    op.create_table('organization_permits',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('organization_id', postgresql.UUID(), nullable=False),
        sa.Column('permit_type', sa.String(length=80), nullable=False),
        sa.Column('reference', sa.String(length=255), nullable=False),
        sa.Column('expires_on', sa.Date(), nullable=True),
        sa.Column('approval_status', sa.String(length=24), nullable=False),
        sa.Column('approved_by', postgresql.UUID(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_organization_permits_organization_id', 'organization_permits', ['organization_id'], unique=False)
    op.create_table('billing_contracts',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('hospital_org_id', postgresql.UUID(), nullable=False),
        sa.Column('billing_anchor_local', sa.Date(), nullable=False),
        sa.Column('cycle_days', sa.Integer(), nullable=False),
        sa.Column('due_days', sa.Integer(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['hospital_org_id'], ['organizations.id']),
    )
    op.create_index('ix_billing_contracts_hospital_org_id', 'billing_contracts', ['hospital_org_id'], unique=False)
    op.create_table('contract_rates',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('contract_id', postgresql.UUID(), nullable=False),
        sa.Column('category_id', postgresql.UUID(), nullable=False),
        sa.Column('collection_rate', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('treatment_rate', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('platform_rate', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.UniqueConstraint('contract_id','category_id','effective_from'),
        sa.ForeignKeyConstraint(['category_id'], ['waste_categories.id']),
        sa.CheckConstraint('collection_rate >= 0 AND treatment_rate >= 0 AND platform_rate >= 0', name='ck_nonnegative_rates'),
        sa.ForeignKeyConstraint(['contract_id'], ['billing_contracts.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_contract_rates_contract_id', 'contract_rates', ['contract_id'], unique=False)
    op.create_table('hospital_invoices',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('contract_id', postgresql.UUID(), nullable=False),
        sa.Column('hospital_org_id', postgresql.UUID(), nullable=False),
        sa.Column('cycle_number', sa.Integer(), nullable=False),
        sa.Column('cycle_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cycle_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('gross_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('credits_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('due_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('paid_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('state', sa.String(length=24), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['hospital_org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['contract_id'], ['billing_contracts.id']),
        sa.UniqueConstraint('contract_id','cycle_number'),
    )
    op.create_index('ix_hospital_invoices_contract_id', 'hospital_invoices', ['contract_id'], unique=False)
    op.create_index('ix_hospital_invoices_hospital_org_id', 'hospital_invoices', ['hospital_org_id'], unique=False)
    op.create_table('invoice_lines',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('invoice_id', postgresql.UUID(), nullable=False),
        sa.Column('waste_record_id', postgresql.UUID(), nullable=False),
        sa.Column('measured_kg', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('collection_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('treatment_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('platform_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('total_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['waste_record_id'], ['waste_records.id']),
        sa.ForeignKeyConstraint(['invoice_id'], ['hospital_invoices.id']),
        sa.UniqueConstraint('waste_record_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_invoice_lines_invoice_id', 'invoice_lines', ['invoice_id'], unique=False)
    op.create_table('recycling_sales',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('facility_org_id', postgresql.UUID(), nullable=False),
        sa.Column('source_reference', sa.String(length=120), nullable=False),
        sa.Column('clearance_reference', sa.String(length=120), nullable=False),
        sa.Column('buyer_invoice_ref', sa.String(length=120), nullable=False),
        sa.Column('proceeds_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('approved_costs_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('sale_payment_verified', sa.Boolean(), nullable=False),
        sa.Column('approved_by', postgresql.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_reference'),
        sa.ForeignKeyConstraint(['facility_org_id'], ['organizations.id']),
    )
    op.create_table('recycling_allocations',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('sale_id', postgresql.UUID(), nullable=False),
        sa.Column('hospital_org_id', postgresql.UUID(), nullable=False),
        sa.Column('contribution_kg', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('hospital_credit_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('credit_remaining_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('facility_share_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('platform_share_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['sale_id'], ['recycling_sales.id']),
        sa.UniqueConstraint('sale_id','hospital_org_id'),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['hospital_org_id'], ['organizations.id']),
    )
    op.create_index('ix_recycling_allocations_sale_id', 'recycling_allocations', ['sale_id'], unique=False)
    op.create_table('operator_job_events',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('organization_id', postgresql.UUID(), nullable=False),
        sa.Column('job_reference', sa.String(length=120), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('reversed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id','job_reference'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
    )
    op.create_table('subscriptions',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('organization_id', postgresql.UUID(), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('price_bdt', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('state', sa.String(length=24), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('organization_id','period_start'),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
    )
    op.create_index('ix_subscriptions_organization_id', 'subscriptions', ['organization_id'], unique=False)
    op.create_table('journals',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('unique_event', sa.String(length=180), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('unique_event'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table('journal_lines',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('journal_id', postgresql.UUID(), nullable=False),
        sa.Column('account', sa.String(length=80), nullable=False),
        sa.Column('organization_id', postgresql.UUID(), nullable=True),
        sa.Column('side', sa.String(length=6), nullable=False),
        sa.Column('amount_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['journal_id'], ['journals.id']),
        sa.CheckConstraint('amount_bdt > 0', name='ck_journal_positive'),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
    )
    op.create_index('ix_journal_lines_journal_id', 'journal_lines', ['journal_id'], unique=False)
    op.create_table('payment_intents',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('payer_user_id', postgresql.UUID(), nullable=False),
        sa.Column('organization_id', postgresql.UUID(), nullable=False),
        sa.Column('target_kind', sa.String(length=24), nullable=False),
        sa.Column('target_id', postgresql.UUID(), nullable=False),
        sa.Column('idempotency_key', sa.String(length=100), nullable=False),
        sa.Column('merchant_reference', sa.String(length=64), nullable=False),
        sa.Column('gateway', sa.String(length=30), nullable=False),
        sa.Column('mode', sa.String(length=12), nullable=False),
        sa.Column('requested_channel', sa.String(length=16), nullable=False),
        sa.Column('amount_bdt', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('state', sa.String(length=24), nullable=False),
        sa.Column('callback_nonce', sa.String(length=100), nullable=False),
        sa.Column('provider_transaction_id', sa.String(length=120), nullable=True),
        sa.Column('provider_session_id', sa.String(length=120), nullable=True),
        sa.Column('redirect_url', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['payer_user_id'], ['users.id']),
        sa.UniqueConstraint('merchant_reference'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.UniqueConstraint('provider_transaction_id'),
        sa.UniqueConstraint('payer_user_id','idempotency_key'),
    )
    op.create_index('ix_payment_intents_payer_user_id', 'payment_intents', ['payer_user_id'], unique=False)
    op.create_table('event_outbox',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('dedupe_key', sa.String(length=180), nullable=False),
        sa.Column('topic', sa.String(length=100), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dedupe_key'),
    )
    op.add_column('vehicles', sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_vehicles_organization', 'vehicles', 'organizations', ['organization_id'], ['id'])
    op.create_index('ix_vehicles_organization_id','vehicles',['organization_id'])
    op.execute("""INSERT INTO organizations (id, name, org_type, status, owner_user_id)
        SELECT id, full_name || ' Collection Company', 'COLLECTION_COMPANY', 'pending', id
        FROM users WHERE role = 'COLLECTOR' AND NOT EXISTS
        (SELECT 1 FROM organizations o WHERE o.owner_user_id = users.id AND o.org_type = 'COLLECTION_COMPANY')""")
    op.execute("""INSERT INTO organizations (id, name, org_type, status, owner_user_id)
        SELECT h.id, h.name, 'HOSPITAL', 'pending', h.user_id FROM hospital_profiles h
        WHERE NOT EXISTS (SELECT 1 FROM organizations o WHERE o.owner_user_id=h.user_id AND o.org_type='HOSPITAL')""")
    op.execute("""INSERT INTO organizations (id, name, org_type, status, owner_user_id)
        SELECT f.id, f.name, 'TREATMENT_FACILITY', 'pending', f.user_id FROM facility_profiles f
        WHERE NOT EXISTS (SELECT 1 FROM organizations o WHERE o.owner_user_id=f.user_id AND o.org_type='TREATMENT_FACILITY')""")
    op.execute("""INSERT INTO organization_members (id, organization_id, user_id, member_role, active)
        SELECT id, id, owner_user_id, 'owner', true FROM organizations
        WHERE org_type IN ('COLLECTION_COMPANY','HOSPITAL','TREATMENT_FACILITY') ON CONFLICT (organization_id, user_id) DO NOTHING""")
    op.execute("""UPDATE vehicles v SET organization_id = o.id FROM organizations o
        WHERE o.owner_user_id = v.assigned_collector_id AND o.org_type = 'COLLECTION_COMPANY'
        AND v.organization_id IS NULL""")

def downgrade():
    op.drop_index('ix_vehicles_organization_id','vehicles')
    op.drop_constraint('fk_vehicles_organization','vehicles',type_='foreignkey')
    op.drop_column('vehicles','organization_id')
    op.drop_table('event_outbox')
    op.drop_table('payment_intents')
    op.drop_table('journal_lines')
    op.drop_table('journals')
    op.drop_table('subscriptions')
    op.drop_table('operator_job_events')
    op.drop_table('recycling_allocations')
    op.drop_table('recycling_sales')
    op.drop_table('invoice_lines')
    op.drop_table('hospital_invoices')
    op.drop_table('contract_rates')
    op.drop_table('billing_contracts')
    op.drop_table('organization_permits')
    op.drop_table('organization_members')
    op.drop_table('organizations')
