"""Behavioral regressions for production workflows (external gateway is stubbed)."""
import uuid
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.api import payments
from app.api.deps import get_current_user
from app.core.db import Base, get_db
from app.core.middleware import RequestBodyLimitMiddleware
from app.core.config import Settings
from app.models.business import Organization, OrganizationMember, PaymentIntent, Subscription, Journal, JournalLine
from app.models.user import User
from app.models.roles import UserRole
from app.models.waste_record import WasteRecord
from app.models.waste_enums import WasteStatus
from app.services.payment_gateway import GatewaySession, GatewayFailure, VerifiedPayment
from app.services.review_guard import lock_reviewable
from app.services.auth_service import AuthService
from app.core.security import hash_password


@pytest.fixture
def context(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    user = User(email='payer@example.org', full_name='Finance Owner', hashed_password=hash_password('SecurePassword123'), role=UserRole.COLLECTOR)
    db.add(user); db.flush()
    org = Organization(name='Collection Company', org_type='COLLECTION_COMPANY', status='verified', owner_user_id=user.id)
    db.add(org); db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, member_role='owner', active=True))
    sub = Subscription(organization_id=org.id, period_start=date(2026,10,1), period_end=date(2026,11,1), price_bdt=Decimal('750.00'), state='unpaid')
    db.add(sub); db.commit()
    cfg = SimpleNamespace(payment_mode='sandbox', payment_live_approved=False,
        payment_public_base_url='https://portal.example.org', frontend_public_base_url='https://portal.example.org', payment_contact_phone='01700000000')
    monkeypatch.setattr(payments, 'get_settings', lambda: cfg)
    adapter = SimpleNamespace(initiate=lambda **kwargs: GatewaySession('https://sandbox.sslcommerz.com/checkout', 'SESSION1'), query=lambda **kwargs: None)
    monkeypatch.setattr(payments, 'gateway', lambda: adapter)
    app=FastAPI(); app.include_router(payments.router, prefix='/api/v1')
    app.dependency_overrides[get_current_user]=lambda:user
    app.dependency_overrides[get_db]=lambda:db
    with TestClient(app) as client:
        yield SimpleNamespace(db=db, user=user, org=org, sub=sub, cfg=cfg, adapter=adapter, client=client)
    db.close();engine.dispose()


def checkout(c, key='checkout-key-123456'):
    return c.client.post('/api/v1/payments/checkout',json={
        'target_kind':'subscription','target_id':str(c.sub.id),'channel':'bkash','idempotency_key':key})


def receipt(row, **changes):
    good=VerifiedPayment(reference=row.merchant_reference, provider_transaction_id='BANK-VERIFIED-001',
        amount_bdt=row.amount_bdt, currency='BDT', status='VALID', risk_level=0)
    return replace(good, **changes)


def test_checkout_persists_before_provider_call(context):
    c=context
    def initiate(**kwargs):
        saved=c.db.scalar(select(PaymentIntent))
        assert saved.state=='created' and saved.merchant_reference==kwargs['reference']
        assert c.sub.state=='unpaid'
        return GatewaySession('https://sandbox.sslcommerz.com/checkout','SESSION1')
    c.adapter.initiate=initiate
    response=checkout(c)
    assert response.status_code==201, response.text
    row=c.db.scalar(select(PaymentIntent))
    assert row.state=='pending' and row.provider_session_id=='SESSION1'
    assert c.sub.state=='unpaid'


def test_timeout_keeps_reconcilable_reference(context):
    c=context
    def timeout(**kwargs):raise GatewayFailure('Provider timed out')
    c.adapter.initiate=timeout
    assert checkout(c).status_code==502
    row=c.db.scalar(select(PaymentIntent))
    assert row and row.state=='pending' and row.merchant_reference
    assert c.sub.state=='unpaid'


def test_retry_after_success_returns_original_receipt(context):
    c=context
    first=checkout(c).json()
    row=c.db.scalar(select(PaymentIntent))
    payments._settle_verified(c.db,row,receipt(row));c.db.commit()
    repeated=checkout(c)
    assert repeated.status_code==201 and repeated.json()['reference']==first['reference']
    assert repeated.json()['state']=='succeeded' and c.sub.state=='paid'
    assert c.db.scalar(select(func.count()).select_from(Journal))==1


def test_distinct_keys_reuse_pending_checkout(context):
    c=context
    first=checkout(c).json()
    second=checkout(c,'another-key-123456').json()
    assert first['reference']==second['reference']
    assert c.db.scalar(select(func.count()).select_from(PaymentIntent))==1


def test_checkout_cannot_reuse_key_for_other_channel(context):
    c=context;checkout(c)
    result=c.client.post('/api/v1/payments/checkout',json={'target_kind':'subscription','target_id':str(c.sub.id),'channel':'nagad','idempotency_key':'checkout-key-123456'})
    assert result.status_code==409


def test_verified_callback_settles_once_and_browser_returns_to_billing(context):
    c=context;checkout(c);row=c.db.scalar(select(PaymentIntent))
    c.adapter.verify=lambda **kwargs:receipt(row)
    data={'tran_id':row.merchant_reference,'val_id':'VALIDATION1','value_a':row.callback_nonce,'status':'VALID'}
    first=c.client.post('/api/v1/payments/success',data=data,follow_redirects=False)
    assert first.status_code==303 and '/dashboard/billing?payment_ref=' in first.headers['location']
    assert c.client.post('/api/v1/payments/ipn',data=data).status_code==200
    assert c.sub.state=='paid'
    assert c.db.scalar(select(func.count()).select_from(Journal))==1
    lines=list(c.db.scalars(select(JournalLine)).all())
    assert sum(x.amount_bdt for x in lines if x.side=='debit')==sum(x.amount_bdt for x in lines if x.side=='credit')==Decimal('750.00')


@pytest.mark.parametrize('bad',[{'amount_bdt':Decimal('1.00')},{'currency':'USD'},{'risk_level':1},{'reference':'OTHER'},{'provider_transaction_id':''}])
def test_provider_mismatch_never_credits_invoice(context,bad):
    c=context;checkout(c);row=c.db.scalar(select(PaymentIntent))
    c.adapter.verify=lambda **kwargs:receipt(row,**bad)
    response=c.client.post('/api/v1/payments/ipn',data={'tran_id':row.merchant_reference,'val_id':'VALIDATION1','value_a':row.callback_nonce})
    assert response.status_code==502
    assert c.sub.state=='unpaid' and row.state=='pending'
    assert c.db.scalar(select(func.count()).select_from(Journal))==0


def test_browser_cancel_does_not_mark_paid_or_failed(context):
    c=context;checkout(c);row=c.db.scalar(select(PaymentIntent))
    response=c.client.post('/api/v1/payments/cancel',data={'tran_id':row.merchant_reference,'value_a':row.callback_nonce},follow_redirects=False)
    assert response.status_code==303 and row.state=='pending' and c.sub.state=='unpaid'


def test_reconciliation_preserves_real_receipt_when_target_was_paid_elsewhere(context):
    c=context;checkout(c);row=c.db.scalar(select(PaymentIntent))
    c.sub.state='paid';c.db.commit()
    payments._settle_verified(c.db,row,receipt(row));c.db.commit()
    assert row.state=='review_required' and row.provider_transaction_id=='BANK-VERIFIED-001'
    assert c.db.scalar(select(func.count()).select_from(Journal))==0


def test_history_requires_current_finance_membership(context):
    c=context;checkout(c)
    membership=c.db.scalar(select(OrganizationMember));membership.active=False;c.db.commit()
    assert c.client.get(f'/api/v1/payments/history?org_id={c.org.id}').status_code==403
    assert checkout(c).status_code==403


def test_no_public_simulated_payment_route(context):
    assert context.client.post('/api/v1/payments/mock/complete',json={'reference':'anything'}).status_code==404


def test_request_limit_applies_without_content_length():
    from starlette.responses import JSONResponse
    app=FastAPI();app.add_middleware(RequestBodyLimitMiddleware,maximum=100)
    @app.post('/upload')
    async def upload():return JSONResponse({'ok':True})
    client=TestClient(app)
    assert client.post('/upload',content=(b'x'*60 for _ in range(3))).status_code==413
    assert client.post('/upload',content=b'x'*101).status_code==413
    assert client.post('/upload',content=b'ok').status_code==200


def test_password_change_revokes_old_session_version(context):
    c=context;version=c.user.auth_version
    AuthService(c.db).change_password(user=c.user,current_password='SecurePassword123',new_password='NewSecurePassword123')
    assert c.user.auth_version==version+1


def test_new_config_disables_unconfigured_checkout():
    assert Settings(_env_file=None, environment='development',payment_mode='disabled').payment_mode=='disabled'
    with pytest.raises(ValueError):Settings(_env_file=None, environment='development',payment_mode='mock')


def test_background_reconciliation_recovers_lost_callback(context, monkeypatch):
    from datetime import timedelta
    from app.services import payment_reconciliation as worker
    c=context;checkout(c);row=c.db.scalar(select(PaymentIntent))
    row.created_at=datetime.now(timezone.utc)-timedelta(minutes=1);c.db.commit()
    c.adapter.query=lambda **kwargs:receipt(row)
    monkeypatch.setattr(worker,'get_settings',lambda:c.cfg)
    monkeypatch.setattr(worker,'gateway_for_settings',lambda cfg:c.adapter)
    result=worker.reconcile_payment_batch(c.db)
    assert result['settled']==1 and row.state=='succeeded' and c.sub.state=='paid'
    assert worker.reconcile_payment_batch(c.db)['checked']==0


def test_background_provider_outage_backs_off_without_credit(context, monkeypatch):
    from datetime import timedelta
    from app.services import payment_reconciliation as worker
    c=context;checkout(c);row=c.db.scalar(select(PaymentIntent))
    row.created_at=datetime.now(timezone.utc)-timedelta(minutes=1);c.db.commit()
    def outage(**kwargs):raise GatewayFailure('Network unavailable')
    c.adapter.query=outage
    monkeypatch.setattr(worker,'get_settings',lambda:c.cfg)
    monkeypatch.setattr(worker,'gateway_for_settings',lambda cfg:c.adapter)
    assert worker.reconcile_payment_batch(c.db)['unavailable']==1
    assert row.state=='pending' and c.sub.state=='unpaid' and row.last_checked_at is not None
    assert worker.reconcile_payment_batch(c.db)['checked']==0


def test_provider_confirmed_failure_is_saved_without_settlement(context):
    c=context;checkout(c);row=c.db.scalar(select(PaymentIntent))
    c.adapter.query=lambda **kwargs:'failed'
    response=c.client.post(f'/api/v1/payments/{row.merchant_reference}/refresh')
    assert response.status_code==200 and response.json()['state']=='failed'
    assert c.sub.state=='unpaid'


def test_bank_receipt_requires_a_different_administrator(context):
    from unit_tests.test_issue14_15_workflow_recycling import seeded_sale,payload,new_user
    from app.api.business import record_sale,submit_recycling_receipt,confirm_recycling_sale,ReceiptEvidenceCreate,VerifySale
    from app.models.business import RecyclingReceiptReview
    c=context
    admin,user,org,fac,hospitals,records,proofs=seeded_sale(c.db)
    sale=record_sale(payload(org,records),user,c.db)
    evidence=ReceiptEvidenceCreate(bank_reference='BANK-RECEIPT-123',received_bdt=Decimal('2000'),received_on=date.today(),evidence_note='Bank statement credit matched against the buyer invoice and transaction reference.')
    submit_recycling_receipt(sale['id'],evidence,admin,c.db)
    with pytest.raises(HTTPException) as denied:
        confirm_recycling_sale(sale['id'],VerifySale(bank_receipt_reference=evidence.bank_reference),admin,c.db)
    assert denied.value.status_code==403
    reviewer=new_user(c.db,'independent-reviewer',UserRole.ADMIN);c.db.commit()
    result=confirm_recycling_sale(sale['id'],VerifySale(bank_receipt_reference=evidence.bank_reference),reviewer,c.db)
    review=c.db.scalar(select(RecyclingReceiptReview))
    assert review.state=='approved' and review.approved_by==reviewer.id and review.submitted_by==admin.id
    assert result['net_profit_bdt']==Decimal('1500.00')


def test_admin_category_codes_match_classifier_and_audit_reference(context):
    from app.services.admin_service import AdminService
    from app.schemas.admin import CategoryCreate, CategoryUpdate
    from app.models.waste_category import WasteCategory
    from app.models.audit_log import AuditLog
    c=context;service=AdminService(c.db)
    category=service.create_category(c.user,CategoryCreate(code='lab_custom',name='Laboratory custom category'))
    assert category.code=='LAB_CUSTOM'
    audit=c.db.scalar(select(AuditLog).where(AuditLog.action=='CATEGORY_CREATED'))
    assert audit.entity_id==str(category.id)
    with pytest.raises(ValueError):service.create_category(c.user,CategoryCreate(code='Lab_Custom',name='Duplicate code'))
    pending=WasteCategory(code='PENDING',name='Pending',is_recyclable=False,is_active=True)
    c.db.add(pending);c.db.commit()
    with pytest.raises(ValueError):service.update_category(c.user,pending.id,CategoryUpdate(is_active=False))
    assert pending.is_active
