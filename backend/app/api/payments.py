"""Durable hosted checkout, verified settlement, history and reconciliation.

There is no public mock completion endpoint. An unavailable merchant leaves
checkout disabled; it never simulates a successful transfer.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import get_settings
from app.core.db import get_db
from app.models.audit_log import AuditLog
from app.models.business import HospitalInvoice, Organization, OrganizationMember, PaymentIntent, Subscription
from app.models.hospital_profile import HospitalProfile
from app.models.roles import UserRole
from app.models.user import User
from app.services.business_finance import bill_due, journal, money, assert_member
from app.services.payment_gateway import GatewayFailure, SSLCommerzGateway, VerifiedPayment
from app.services.payment_settlement import _apply_settlement, _settle_verified

router = APIRouter(prefix="/payments", tags=["payments"])
CHANNEL_LABELS = {"bkash": "bKash", "nagad": "Nagad", "rocket": "Rocket", "card": "Bank card"}


class CheckoutRequest(BaseModel):
    target_kind: str = Field(pattern="^(invoice|subscription)$")
    target_id: uuid.UUID
    channel: str = Field(pattern="^(bkash|nagad|rocket|card)$")
    idempotency_key: str = Field(min_length=12, max_length=100)


def gateway():
    cfg = get_settings()
    if cfg.payment_mode not in {"sandbox", "live"}:
        raise GatewayFailure("Online payments are not configured. Contact your billing administrator.")
    if cfg.payment_mode == "live" and not cfg.payment_live_approved:
        raise GatewayFailure("Live merchant credentials have not been approved")
    return SSLCommerzGateway(mode=cfg.payment_mode, store_id=cfg.sslcz_store_id,
                            store_password=cfg.sslcz_store_password)


def _amount(db: Session, user: User, kind: str, identifier: uuid.UUID):
    cls = HospitalInvoice if kind == "invoice" else Subscription
    target = db.scalar(select(cls).where(cls.id == identifier).with_for_update())
    if not target:
        raise HTTPException(404, "Billing document not found")
    org_id = target.hospital_org_id if kind == "invoice" else target.organization_id
    try:
        org = assert_member(db, user, org_id, {"owner", "manager", "finance"})
    except PermissionError:
        raise HTTPException(403, "Payer organization not authorized")
    # Admin read privileges do not authorize checkout without membership.
    if not db.scalar(select(OrganizationMember.id).where(
        OrganizationMember.organization_id == org_id, OrganizationMember.user_id == user.id,
        OrganizationMember.active.is_(True), OrganizationMember.member_role.in_(["owner", "manager", "finance"]))):
        raise HTTPException(403, "Payer organization not authorized")
    if kind == "invoice":
        if target.state not in {"issued", "partially_paid"}:
            raise HTTPException(409, "Invoice is not payable")
        remaining = bill_due(target.due_bdt, 0, target.paid_bdt)
    else:
        if target.state != "unpaid":
            raise HTTPException(409, "Subscription is not payable")
        remaining = money(target.price_bdt)
    if remaining <= 0:
        raise HTTPException(409, "No outstanding amount")
    return target, org, remaining


def _status(row: PaymentIntent):
    return {"reference": row.merchant_reference, "organization_id": str(row.organization_id),
            "target_kind": row.target_kind, "target_id": str(row.target_id),
            "amount_bdt": str(row.amount_bdt), "currency": "BDT", "mode": row.mode,
            "state": row.state, "channel": row.requested_channel,
            "channel_label": CHANNEL_LABELS.get(row.requested_channel, row.requested_channel),
            "provider_transaction_id": row.provider_transaction_id,
            "created_at": row.created_at, "verified_at": row.verified_at,
            "settled_in_real_money": row.state == "succeeded" and row.mode == "live"}


def _checkout_response(row: PaymentIntent, mode: str | None = None):
    return {**_status(row), "checkout_url": row.redirect_url}


@router.get("/config")
def public_payment_config():
    cfg = get_settings()
    try:
        gateway()
        enabled = cfg.payment_public_base_url.startswith("https://")
    except GatewayFailure:
        enabled = False
    return {"mode": cfg.payment_mode, "enabled": enabled,
            "provider": "SSLCOMMERZ", "channels": list(CHANNEL_LABELS),
            "channel_note": "Payment methods are provided by your merchant's secure hosted checkout."}


@router.get("/history")
def payment_history(org_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        assert_member(db, user, org_id, {"owner", "manager", "finance"})
    except PermissionError:
        raise HTTPException(403, "Finance access denied")
    return [_status(row) for row in db.scalars(select(PaymentIntent).where(
        PaymentIntent.organization_id == org_id).order_by(PaymentIntent.created_at.desc()).limit(100)).all()]


@router.get("/admin/history")
def admin_payment_history(user: User = Depends(require_roles(UserRole.ADMIN)), db: Session = Depends(get_db)):
    return [_status(row) for row in db.scalars(select(PaymentIntent)
        .order_by(PaymentIntent.created_at.desc()).limit(250)).all()]


@router.post("/checkout", status_code=201)
def checkout(payload: CheckoutRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = get_settings()
    try:
        adapter = gateway()
    except GatewayFailure as exc:
        raise HTTPException(503, str(exc))
    if not cfg.payment_public_base_url.startswith("https://"):
        raise HTTPException(503, "Hosted checkout requires an HTTPS callback address")
    # Serialize checkout creation per payer, including first use of an idempotency
    # key. Unlike locking a nonexistent intent, this also handles racing requests.
    db.scalar(select(User).where(User.id == user.id).with_for_update(of=User))
    previous = db.scalar(select(PaymentIntent).where(PaymentIntent.payer_user_id == user.id,
        PaymentIntent.idempotency_key == payload.idempotency_key).with_for_update(of=PaymentIntent))
    if previous:
        if (previous.mode != cfg.payment_mode or previous.target_id != payload.target_id
                or previous.target_kind != payload.target_kind or previous.requested_channel != payload.channel):
            raise HTTPException(409, "Idempotency key already belongs to another checkout")
        try:
            assert_member(db, user, previous.organization_id, {"owner", "manager", "finance"})
        except PermissionError:
            raise HTTPException(403, "Payer organization access was revoked")
        return _checkout_response(previous)
    target, org, amount = _amount(db, user, payload.target_kind, payload.target_id)
    # Reuse a recent pending session rather than open several payment windows
    # for one receivable. The target lock serializes different payer accounts.
    from datetime import timedelta
    pending = db.scalar(select(PaymentIntent).where(
        PaymentIntent.target_kind == payload.target_kind, PaymentIntent.target_id == target.id,
        PaymentIntent.state.in_(["created", "pending"]), PaymentIntent.mode == cfg.payment_mode,
        PaymentIntent.created_at > datetime.now(timezone.utc) - timedelta(minutes=30))
        .order_by(PaymentIntent.created_at.desc()).limit(1))
    if pending:
        if pending.payer_user_id == user.id and pending.redirect_url:
            return _checkout_response(pending)
        raise HTTPException(409, "A checkout is already pending for this document; check payment history before retrying")
    profile = db.scalar(select(HospitalProfile).where(HospitalProfile.organization_id == org.id))
    phone = (profile.phone if profile else cfg.payment_contact_phone) or ""
    if not phone:
        raise HTTPException(422, "Add a billing contact phone before starting checkout")
    reference, nonce = "MW" + uuid.uuid4().hex[:24].upper(), secrets.token_urlsafe(32)
    row = PaymentIntent(payer_user_id=user.id, organization_id=org.id,
        target_kind=payload.target_kind, target_id=target.id, idempotency_key=payload.idempotency_key,
        merchant_reference=reference, gateway="sslcommerz", mode=cfg.payment_mode,
        requested_channel=payload.channel, amount_bdt=amount, callback_nonce=nonce, state="created")
    db.add(row)
    db.commit()  # Persist before any external side effect, even if the process crashes.
    base = cfg.payment_public_base_url.rstrip("/")
    callbacks = {key: f"{base}/api/v1/payments/{key}" for key in ("success", "fail", "cancel", "ipn")}
    customer = {"name": user.full_name, "email": user.email, "phone": phone,
        "address": (profile.address_line if profile else org.name) or org.name,
        "city": (profile.city if profile else "Dhaka") or "Dhaka"}
    try:
        session = adapter.initiate(reference=reference, amount=amount, correlation=nonce,
                                   customer=customer, callbacks=callbacks, channel=payload.channel)
    except GatewayFailure as exc:
        # A timeout is ambiguous: keep the reference reconcilable instead of
        # declaring a transfer failed without asking the provider.
        row.state = "pending"
        db.add(AuditLog(actor_user_id=user.id, action="payment.initiation_uncertain",
            entity_type="payment_intent", entity_id=str(row.id), details={"reference": reference}))
        db.commit()
        raise HTTPException(502, f"{exc}. Reference {reference} was saved; refresh payment history before retrying.")
    row = db.scalar(select(PaymentIntent).where(PaymentIntent.id == row.id)
        .with_for_update(of=PaymentIntent).execution_options(populate_existing=True))
    row.redirect_url, row.provider_session_id = session.redirect_url, session.session_id
    if row.state == "created":
        row.state = "pending"  # A fast IPN may already have settled this intent.
    db.commit()
    return _checkout_response(row)


def _return(reference: str):
    from urllib.parse import urlencode
    return RedirectResponse(get_settings().frontend_public_base_url.rstrip("/")
        + "/dashboard/billing?" + urlencode({"payment_ref": reference}), status_code=303)


@router.post("/ipn")
@router.post("/success")
async def verified_gateway_notification(request: Request, db: Session = Depends(get_db)):
    cfg = get_settings()
    if cfg.payment_mode not in {"sandbox", "live"}:
        raise HTTPException(403, "Hosted payment callbacks are disabled")
    try:
        data = dict(await request.form())
    except Exception:
        raise HTTPException(400, "Invalid gateway notification")
    reference, validation_id, correlation = (str(data.get(k) or "") for k in ("tran_id", "val_id", "value_a"))
    if not reference or not validation_id or not correlation or len(reference) > 64 or len(validation_id) > 120 or len(correlation) > 100:
        raise HTTPException(400, "Missing callback fields")
    row = db.scalar(select(PaymentIntent).where(PaymentIntent.merchant_reference == reference).with_for_update(of=PaymentIntent))
    if not row or not secrets.compare_digest(row.callback_nonce, correlation) or row.mode != cfg.payment_mode:
        raise HTTPException(403, "Unknown or uncorrelated transaction")
    if row.state != "succeeded":
        try:
            verified = await run_in_threadpool(gateway().verify, provider_validation_id=validation_id)
            _settle_verified(db, row, verified)
        except GatewayFailure as exc:
            # An IPN must receive an error so the provider can retry verification.
            raise HTTPException(502, str(exc))
        db.commit()
    if request.url.path.endswith("/success"):
        return _return(reference)
    return {"state": row.state}


@router.post("/fail")
@router.post("/cancel")
async def unverified_return(request: Request, db: Session = Depends(get_db)):
    data = dict(await request.form())
    reference, correlation = str(data.get("tran_id") or ""), str(data.get("value_a") or "")
    row = db.scalar(select(PaymentIntent).where(PaymentIntent.merchant_reference == reference))
    if not row or not secrets.compare_digest(row.callback_nonce, correlation):
        raise HTTPException(403, "Unknown or uncorrelated return")
    # A browser return never changes ledger state. Reconciliation queries the provider.
    return _return(reference)


@router.post("/{reference}/refresh")
def refresh_payment(reference: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _authorized_payment(db, user, reference, lock=True)
    if row.state == "succeeded" or row.mode != get_settings().payment_mode:
        return _status(row)
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    last = row.last_checked_at
    if last is not None:
        last = last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last
        if last > now - timedelta(seconds=10):
            return _status(row)
    row.last_checked_at = now
    row.reconciliation_attempts += 1
    try:
        verified = gateway().query(reference=row.merchant_reference)
        if isinstance(verified, VerifiedPayment):
            _settle_verified(db, row, verified)
        elif verified in {"failed", "cancelled", "expired"}:
            row.state = verified
            db.add(AuditLog(actor_user_id=user.id, action="payment.provider_status",
                entity_type="payment_intent", entity_id=str(row.id), details={"state": verified}))
        db.commit()
    except GatewayFailure as exc:
        db.commit()  # Save check time so a provider outage does not cause a retry storm.
        raise HTTPException(502, str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Provider transaction already recorded; refresh payment history")
    return _status(row)


def _authorized_payment(db, user, reference, *, lock=False):
    stmt = select(PaymentIntent).where(PaymentIntent.merchant_reference == reference)
    row = db.scalar(stmt.with_for_update() if lock else stmt)
    if not row:
        raise HTTPException(404, "Payment not found")
    try:
        assert_member(db, user, row.organization_id, {"owner", "manager", "finance"})
    except PermissionError:
        raise HTTPException(403, "Finance access denied")
    return row


@router.get("/{reference}")
def payment_status(reference: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _status(_authorized_payment(db, user, reference))
