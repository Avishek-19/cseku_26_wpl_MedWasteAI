"""Atomic verified-payment settlement, shared by callbacks and reconciliation."""
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.audit_log import AuditLog
from app.models.business import HospitalInvoice, PaymentIntent, Subscription
from app.services.business_finance import money, journal
from app.services.payment_gateway import assert_verified_matches_intent


def _apply_settlement(db: Session, row: PaymentIntent, *, demo: bool) -> None:
    """Settle exactly once under a target-row lock; never over-credit receivables.

    A second completed checkout for the same invoice must go to manual refund/
    reconciliation instead of creating extra journal entries. This lock also
    protects against separate intents racing to settle the same target.
    """
    if row.mode == "mock" or demo:
        raise HTTPException(403, "Simulated settlement is disabled")
    if row.state == "succeeded":
        return
    tag = "SANDBOX " if row.mode == "sandbox" else ""
    if row.target_kind == "invoice":
        target = db.scalar(select(HospitalInvoice).where(HospitalInvoice.id == row.target_id).with_for_update(of=HospitalInvoice))
        if not target or target.hospital_org_id != row.organization_id:
            raise HTTPException(409, "Invalid invoice")
        if target.state not in {"issued", "partially_paid", "paid"}:
            raise HTTPException(409, "Invoice is not payable")
        outstanding = money(target.due_bdt) - money(target.paid_bdt)
        if outstanding <= 0 or money(row.amount_bdt) > outstanding:
            raise HTTPException(409, "Invoice settlement exceeds outstanding amount; manual reconciliation required")
        target.paid_bdt = money(target.paid_bdt) + money(row.amount_bdt)
        if money(target.paid_bdt) == money(target.due_bdt):
            target.state = "paid"
        else:
            target.state = "partially_paid"
        journal(
            db,
            unique_event=f"payment:{row.id}",
            description=f"{tag}hospital invoice payment via {row.requested_channel}",
            entries=[
                ("bank_gateway_clearing", "debit", row.amount_bdt, row.organization_id),
                ("hospital_receivable", "credit", row.amount_bdt, row.organization_id),
            ],
        )
    else:
        target = db.scalar(select(Subscription).where(Subscription.id == row.target_id).with_for_update(of=Subscription))
        if not target or target.organization_id != row.organization_id:
            raise HTTPException(409, "Invalid subscription")
        if target.state != "unpaid" or money(target.price_bdt) != money(row.amount_bdt):
            raise HTTPException(409, "Subscription already paid or amount changed; manual reconciliation required")
        target.state = "paid"
        journal(
            db,
            unique_event=f"payment:{row.id}",
            description=f"{tag}subscription payment via {row.requested_channel}",
            entries=[
                ("bank_gateway_clearing", "debit", row.amount_bdt, row.organization_id),
                ("subscription_revenue", "credit", row.amount_bdt, row.organization_id),
            ],
        )
    row.state = "succeeded"
    row.verified_at = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            actor_user_id=row.payer_user_id,
            action="payment.provider_verified",
            entity_type="payment_intent",
            entity_id=str(row.id),
            details={
                "gateway": row.gateway,
                "reference": row.merchant_reference,
                "mode": row.mode,
                "channel": row.requested_channel,
                "real_money": row.mode == "live",
            },
        )
    )


def _settle_verified(db, row, verified):
    assert_verified_matches_intent(verified, expected_reference=row.merchant_reference,
                                   expected_amount=row.amount_bdt)
    duplicate = db.scalar(select(PaymentIntent.id).where(
        PaymentIntent.provider_transaction_id == verified.provider_transaction_id,
        PaymentIntent.id != row.id).limit(1))
    if duplicate:
        raise HTTPException(409, "Provider transaction is already associated with another payment")
    if row.state == "succeeded":
        return
    # Keep a verified receipt even when an outdated target needs reconciliation.
    # The settlement savepoint rolls back any invoice/journal mutations only.
    row.provider_transaction_id = verified.provider_transaction_id
    row.verified_at = datetime.now(timezone.utc)
    db.flush()
    try:
        with db.begin_nested():
            _apply_settlement(db, row, demo=False)
    except HTTPException as exc:
        row.state = "review_required"
        db.add(AuditLog(actor_user_id=row.payer_user_id, action="payment.reconciliation_required",
            entity_type="payment_intent", entity_id=str(row.id),
            details={"reference": row.merchant_reference, "reason": str(exc.detail)}))


