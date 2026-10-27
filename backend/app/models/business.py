"""Additive company, billing, financial and payment schema.

Store BDT as NUMERIC, no editable wallet balances. Status strings are explicit
so migrations add new states without rewriting existing PostgreSQL ENUM types.
"""
import uuid
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
                        JSON, Integer, Numeric, String, Text, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base


def pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def date_created():
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Organization(Base):
    __tablename__ = 'organizations'
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    org_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='pending', index=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, index=True)
    created_at: Mapped[datetime] = date_created()


class OrganizationMember(Base):
    __tablename__ = 'organization_members'
    __table_args__ = (UniqueConstraint('organization_id','user_id'),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, index=True)
    member_role: Mapped[str] = mapped_column(String(20), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = date_created()


class OrganizationPermit(Base):
    __tablename__ = 'organization_permits'
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False, index=True)
    permit_type: Mapped[str] = mapped_column(String(80), nullable=False)
    reference: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_on: Mapped[date | None] = mapped_column(Date)
    approval_status: Mapped[str] = mapped_column(String(24), nullable=False, default='pending')
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BillingContract(Base):
    __tablename__ = 'billing_contracts'
    id: Mapped[uuid.UUID] = pk()
    hospital_org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False, index=True)
    billing_anchor_local: Mapped[date] = mapped_column(Date, nullable=False)
    cycle_days: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    due_days: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = date_created()


class ContractRate(Base):
    __tablename__ = 'contract_rates'
    __table_args__ = (UniqueConstraint('contract_id','category_id','effective_from'),
        CheckConstraint('collection_rate >= 0 AND treatment_rate >= 0 AND platform_rate >= 0', name='ck_nonnegative_rates'))
    id: Mapped[uuid.UUID] = pk()
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('billing_contracts.id'), nullable=False, index=True)
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('waste_categories.id'), nullable=False)
    collection_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    treatment_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    platform_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)


class HospitalInvoice(Base):
    __tablename__ = 'hospital_invoices'
    __table_args__ = (UniqueConstraint('contract_id','cycle_number'),)
    id: Mapped[uuid.UUID] = pk()
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('billing_contracts.id'), nullable=False, index=True)
    hospital_org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False, index=True)
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False)
    cycle_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cycle_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gross_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    credits_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    due_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    paid_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal('0'))
    state: Mapped[str] = mapped_column(String(24), nullable=False, default='issued')
    issued_at: Mapped[datetime] = date_created()


class InvoiceLine(Base):
    __tablename__ = 'invoice_lines'
    __table_args__ = (UniqueConstraint('waste_record_id'),)
    id: Mapped[uuid.UUID] = pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('hospital_invoices.id'), nullable=False, index=True)
    waste_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('waste_records.id'), nullable=False)
    measured_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    collection_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    treatment_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    platform_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)


class InvoiceAdjustment(Base):
    """Append-only audit of additional verified services billed after issuance.

    Source invoice journals never change. These adjustment entries tie the
    refreshed unpaid invoice's materialized totals to their exact added batch.
    """
    __tablename__ = 'invoice_adjustments'
    __table_args__ = (UniqueConstraint('waste_record_id', name='uq_invoice_adjustment_batch'),)
    id: Mapped[uuid.UUID] = pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('hospital_invoices.id', ondelete='RESTRICT'), nullable=False, index=True)
    waste_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('waste_records.id', ondelete='RESTRICT'), nullable=False)
    measured_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    collection_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    treatment_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    platform_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(160), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at: Mapped[datetime] = date_created()


class RecyclingSale(Base):
    __tablename__ = 'recycling_sales'
    id: Mapped[uuid.UUID] = pk()
    facility_org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    clearance_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    buyer_invoice_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    proceeds_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    approved_costs_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    sale_payment_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'))
    created_at: Mapped[datetime] = date_created()


class RecyclingSaleLot(Base):
    """Immutable verified input batch assigned to exactly one recycling sale.

    contribution_kg is a snapshot of facility-measured received kg. It is a
    proportional *input* basis, not a claim of recovered resale yield.
    """
    __tablename__ = 'recycling_sale_lots'
    __table_args__ = (
        UniqueConstraint('waste_record_id', name='uq_recycling_sale_lot_waste_record'),
        CheckConstraint('contribution_kg > 0', name='ck_recycling_lot_positive_kg'),
    )
    id: Mapped[uuid.UUID] = pk()
    sale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('recycling_sales.id', ondelete='RESTRICT'), nullable=False, index=True)
    waste_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('waste_records.id', ondelete='RESTRICT'), nullable=False)
    hospital_org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False, index=True)
    contribution_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    created_at: Mapped[datetime] = date_created()


class RecyclingAllocation(Base):
    __tablename__ = 'recycling_allocations'
    __table_args__ = (UniqueConstraint('sale_id','hospital_org_id'),)
    id: Mapped[uuid.UUID] = pk()
    sale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('recycling_sales.id'), nullable=False, index=True)
    hospital_org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False)
    contribution_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    hospital_credit_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    credit_remaining_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    facility_share_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    platform_share_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)


class OperatorJobEvent(Base):
    __tablename__ = 'operator_job_events'
    __table_args__ = (UniqueConstraint('organization_id','job_reference'),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False)
    job_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    verified_at: Mapped[datetime] = date_created()
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Subscription(Base):
    __tablename__ = 'subscriptions'
    __table_args__ = (UniqueConstraint('organization_id','period_start'),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False, index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    price_bdt: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default='unpaid')
    created_at: Mapped[datetime] = date_created()


class Journal(Base):
    __tablename__ = 'journals'
    id: Mapped[uuid.UUID] = pk()
    unique_event: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = date_created()


class JournalLine(Base):
    __tablename__ = 'journal_lines'
    __table_args__ = (CheckConstraint('amount_bdt > 0', name='ck_journal_positive'),)
    id: Mapped[uuid.UUID] = pk()
    journal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('journals.id'), nullable=False, index=True)
    account: Mapped[str] = mapped_column(String(80), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'))
    side: Mapped[str] = mapped_column(String(6), nullable=False)
    amount_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)


class PaymentIntent(Base):
    __tablename__ = 'payment_intents'
    __table_args__ = (UniqueConstraint('payer_user_id','idempotency_key'),
        Index('ix_payment_reconciliation', 'state', 'last_checked_at'))
    id: Mapped[uuid.UUID] = pk()
    payer_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    merchant_reference: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    gateway: Mapped[str] = mapped_column(String(30), nullable=False)
    mode: Mapped[str] = mapped_column(String(12), nullable=False)
    requested_channel: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default='created')
    callback_nonce: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    provider_session_id: Mapped[str | None] = mapped_column(String(120))
    redirect_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = date_created()
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconciliation_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class EventOutbox(Base):
    __tablename__ = 'event_outbox'
    id: Mapped[uuid.UUID] = pk()
    dedupe_key: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(320), nullable=True)
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = date_created()


class OrganizationInvitation(Base):
    """Pending invite for a user to join an organization with a specific member role."""
    __tablename__ = 'organization_invitations'
    __table_args__ = (
        UniqueConstraint('organization_id', 'email', name='uq_org_invite_email'),
        Index('ix_org_invitations_token', 'token', unique=True),
    )
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    member_role: Mapped[str] = mapped_column(String(20), nullable=False)  # owner/manager/dispatcher/driver/finance/worker
    token: Mapped[str] = mapped_column(String(64), nullable=False)
    invited_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='pending')  # pending/accepted/revoked/expired
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = date_created()


class RecyclingReceiptReview(Base):
    """Bank evidence submitted by one administrator and approved by another."""
    __tablename__ = 'recycling_receipt_reviews'
    __table_args__ = (CheckConstraint('received_bdt > 0', name='ck_receipt_positive'),)
    id: Mapped[uuid.UUID] = pk()
    sale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('recycling_sales.id', ondelete='RESTRICT'), nullable=False, unique=True)
    bank_reference: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    received_bdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    evidence_note: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'))
    state: Mapped[str] = mapped_column(String(24), nullable=False, default='pending')
    created_at: Mapped[datetime] = date_created()
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
