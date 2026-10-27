"""Issue 14/15 isolated regression: durable DLQ and verified recycling lots."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.core.db import Base
from app.models.roles import UserRole
from app.models.user import User
from app.models.audit_log import AuditLog
from app.models.business import (
    EventOutbox, Organization, OrganizationMember,
    RecyclingSale, RecyclingSaleLot, RecyclingAllocation, Journal,
)
from app.models.waste_enums import WasteStatus, WasteUnit
from app.models.waste_category import WasteCategory
from app.models.waste_record import WasteRecord
from app.models.hospital_profile import HospitalProfile
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.processing_record import ProcessingRecord
from app.services import workflow_orchestrator
from app.services.business_finance import verified_recycling_lot_basis, record_recycling_distribution
from app.api.admin import DeadLetterRetryRequest, requeue_workflow_dead_letter, list_workflow_dead_letters
from app.api.business import RecyclingCreate, VerifySale, record_sale, confirm_recycling_sale


@pytest.fixture
def db():
    engine = create_engine('sqlite+pysqlite:///:memory:',
        connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def new_user(db, name, role):
    user=User(email=f'{name}@example.org', full_name=name,hashed_password='x',role=role,is_active=True)
    db.add(user);db.flush();return user


def new_org(db, owner, org_type):
    org=Organization(name=f'Org {uuid.uuid4().hex[:8]}',org_type=org_type,status='verified',owner_user_id=owner.id)
    db.add(org);db.flush()
    db.add(OrganizationMember(organization_id=org.id,user_id=owner.id,member_role='owner',active=True))
    return org


def dead_item(db, name='DLQ'):
    item=EventOutbox(dedupe_key=f'{name}:{uuid.uuid4()}',topic='waste.report.progress',
        payload={'record_id':str(uuid.uuid4()),'user_id':str(uuid.uuid4())})
    db.add(item);db.commit();return item


def test_dead_letter_only_after_fifth_failed_attempt(db):
    item=dead_item(db)
    with patch.object(workflow_orchestrator,'process_one',side_effect=RuntimeError('secret-token-not-to-log')):
        for attempt in range(1,6):
            result=workflow_orchestrator.run_workflow_batch(db)
            db.refresh(item)
            assert result['retry']==1
            assert item.attempts==attempt
            assert item.lease_owner is None and item.lease_expires_at is None
            assert item.last_error=='RuntimeError'
            assert 'secret-token' not in item.last_error
            assert bool(item.dead_lettered_at)==(attempt==5)
            assert item.topic==('waste.report.dead_letter' if attempt==5 else 'waste.report.progress')
        assert workflow_orchestrator.run_workflow_batch(db)['retry']==0
        assert item.attempts==5


def test_dead_letter_admin_can_requeue_with_audit_but_cannot_requeue_twice(db):
    actor=new_user(db,'administrator',UserRole.ADMIN)
    item=dead_item(db)
    item.topic='waste.report.dead_letter';item.attempts=5
    item.last_error='RuntimeError';item.dead_lettered_at=datetime.now(timezone.utc)
    db.commit()
    rows=list_workflow_dead_letters(100,actor,db)
    assert rows[0]['id']==str(item.id) and rows[0]['attempts']==5
    result=requeue_workflow_dead_letter(item.id,DeadLetterRetryRequest(reason='Fixed hospital profile config'),actor,db)
    assert result['status']=='queued'
    db.refresh(item)
    assert item.attempts==0 and item.dead_lettered_at is None and item.last_error is None
    assert item.topic=='waste.report.progress'
    audit=db.scalar(select(AuditLog).where(AuditLog.action=='workflow.dead_letter.requeue'))
    assert audit.actor_user_id==actor.id and audit.details['previous_attempts']==5
    with pytest.raises(HTTPException) as exc:
        requeue_workflow_dead_letter(item.id,DeadLetterRetryRequest(reason='Retry same event again'),actor,db)
    assert exc.value.status_code==409


def test_dead_letter_lease_cannot_be_requeued(db):
    actor=new_user(db,'administrator',UserRole.ADMIN)
    item=dead_item(db)
    item.topic='waste.report.dead_letter';item.lease_owner='another-worker'
    db.commit()
    with pytest.raises(HTTPException) as exc:
        requeue_workflow_dead_letter(item.id, DeadLetterRetryRequest(reason='Confirmed root cause repaired'), actor, db)
    assert exc.value.status_code==409


def seeded_sale(db, weights=(Decimal('4.50'), Decimal('5.50'))):
    admin=new_user(db,'admin2',UserRole.ADMIN)
    facility_user=new_user(db,'facility2',UserRole.FACILITY)
    fac_org=new_org(db,facility_user,'TREATMENT_FACILITY')
    fac=TreatmentFacilityProfile(user_id=facility_user.id, organization_id=fac_org.id,
        name='Recycling Facility',registration_number='F-1',contact_person='Manager', phone='1',
        address_line='Here',city='Khulna',region='Khulna',postal_code='9000',
        capacity_kg=Decimal('300'),current_utilization_kg=Decimal('0'),is_verified=True,
        processing_services=['RECYCLING'])
    db.add(fac);db.flush()
    cat=WasteCategory(code='REC-'+uuid.uuid4().hex[:9],name='Recyclable test '+uuid.uuid4().hex[:9],is_recyclable=True)
    db.add(cat);db.flush()
    records=[]; orgs=[]; processing=[]
    for i,weight in enumerate(weights):
        owner=new_user(db,f'hospital{i}-{uuid.uuid4().hex[:6]}',UserRole.HOSPITAL)
        org=new_org(db,owner,'HOSPITAL')
        profile=HospitalProfile(user_id=owner.id,organization_id=org.id,
            name=f'Hospital {i}',registration_number=f'H{i}',contact_person='Owner',phone='1',
            address_line='Road',city='Khulna',region='Khulna',postal_code='9000')
        db.add(profile);db.flush()
        rec=WasteRecord(waste_code='REC-'+uuid.uuid4().hex[:12],hospital_id=profile.id,
            category_id=cat.id,reported_by=owner.id,quantity=weight,received_quantity=weight,
            unit=WasteUnit.KG,generated_at=datetime.now(timezone.utc),status=WasteStatus.COMPLETED)
        db.add(rec);db.flush()
        proof=ProcessingRecord(waste_record_id=rec.id,facility_id=fac.id,
            processing_method='RECYCLING',status='completed',completed_at=datetime.now(timezone.utc))
        db.add(proof)
        records.append(rec);orgs.append(org);processing.append(proof)
    db.commit()
    return admin,facility_user,fac_org,fac,orgs,records,processing


def payload(fac_org,records):
    return RecyclingCreate(facility_org_id=fac_org.id,source_reference='lot-'+uuid.uuid4().hex,
        clearance_reference='clearance-001',buyer_invoice_ref='invoice-001',
        proceeds_bdt=Decimal('2000.00'),approved_costs_bdt=Decimal('500.00'),
        waste_record_ids=[rec.id for rec in records])


def test_recycling_distribution_is_verified_weighted_and_balanced(db):
    admin,user,org,fac,hospitals,records,proofs=seeded_sale(db)
    data=record_sale(payload(org,records),user,db)
    lots=list(db.scalars(select(RecyclingSaleLot).where(RecyclingSaleLot.sale_id==data['id'])).all())
    assert len(lots)==2
    assert {lot.contribution_kg for lot in lots}=={Decimal('4.50'),Decimal('5.50')}
    sale=db.get(RecyclingSale,data['id'])
    assert verified_recycling_lot_basis(db,sale)=={hospitals[0].id:Decimal('4.50'),hospitals[1].id:Decimal('5.50')}
    response=confirm_recycling_sale(sale.id,VerifySale(bank_receipt_reference='receipt-00001'),admin,db)
    allocations={r['hospital_org_id']:r for r in response['allocations']}
    assert response['net_profit_bdt']==Decimal('1500.00')
    assert allocations[hospitals[0].id]['hospital_credit_bdt']==Decimal('405.00')
    assert allocations[hospitals[1].id]['hospital_credit_bdt']==Decimal('495.00')
    assert sum(r['facility_share_bdt'] for r in allocations.values())==Decimal('450.00')
    assert sum(r['platform_share_bdt'] for r in allocations.values())==Decimal('150.00')
    assert db.scalar(select(Journal).where(Journal.unique_event==f'recycle_distribution:{sale.id}')) is not None
    with pytest.raises(HTTPException) as exc:
        confirm_recycling_sale(sale.id,VerifySale(bank_receipt_reference='receipt-00001'),admin,db)
    assert exc.value.status_code==409


def test_fake_admin_weights_are_rejected_even_in_demo(db):
    with pytest.raises(ValidationError):
        VerifySale(bank_receipt_reference='receipt-00001',hospital_contribution_kg={str(uuid.uuid4()):1})


def test_duplicate_batches_in_single_sale_are_rejected(db):
    admin,user,org,fac,hospitals,records,proofs=seeded_sale(db)
    data=payload(org,records)
    data.waste_record_ids=[records[0].id,records[0].id]
    with pytest.raises(HTTPException) as exc:
        record_sale(data,user,db)
    assert exc.value.status_code==422
    assert db.scalar(select(RecyclingSale.id)) is None


def test_batch_cannot_be_sold_twice(db):
    admin,user,org,fac,hospitals,records,proofs=seeded_sale(db)
    record_sale(payload(org,records),user,db)
    with pytest.raises(HTTPException) as exc:
        record_sale(payload(org,records),user,db)
    assert exc.value.status_code==409
    assert len(db.scalars(select(RecyclingSale.id)).all())==1


@pytest.mark.parametrize('invalid', ['not_completed','wrong_facility','missing_proof','not_recycling','not_kg','unmeasured'])
def test_unverified_recycling_bases_are_rejected_before_sale(db,invalid):
    admin,user,org,fac,hospitals,records,proofs=seeded_sale(db)
    if invalid=='not_completed':records[0].status=WasteStatus.PROCESSING
    elif invalid=='wrong_facility':proofs[0].facility_id=uuid.uuid4()
    elif invalid=='missing_proof':db.delete(proofs[0])
    elif invalid=='not_recycling':proofs[0].processing_method='INCINERATION'
    elif invalid=='not_kg':records[0].unit=WasteUnit.PCS
    elif invalid=='unmeasured':records[0].received_quantity=None
    db.commit()
    with pytest.raises(HTTPException) as exc:
        record_sale(payload(org,records),user,db)
    assert exc.value.status_code==409
    assert not db.scalars(select(RecyclingSale.id)).all()


def test_changed_verified_weight_blocks_receipt_before_any_journal(db):
    admin,user,org,fac,hospitals,records,proofs=seeded_sale(db)
    data=record_sale(payload(org,records),user,db)
    sale_id=data['id']
    records[0].received_quantity=Decimal('20.0')
    db.commit()
    with pytest.raises(HTTPException) as exc:
        confirm_recycling_sale(sale_id,VerifySale(bank_receipt_reference='receipt-00001'),admin,db)
    assert exc.value.status_code==409
    assert db.get(RecyclingSale,sale_id).sale_payment_verified is False
    assert not db.scalars(select(RecyclingAllocation.id)).all()
    assert not db.scalars(select(Journal.id)).all()


def test_admin_dead_letter_routes_require_admin_account(db):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user
    from app.core.db import get_db
    admin=new_user(db, 'admin-routes', UserRole.ADMIN)
    hospital=new_user(db,'hospital-routes',UserRole.HOSPITAL)
    event=dead_item(db)
    event.topic='waste.report.dead_letter'; event.attempts=5; event.dead_lettered_at=datetime.now(timezone.utc)
    db.commit()
    selected={'user':hospital}
    app.dependency_overrides[get_db]=lambda: db
    app.dependency_overrides[get_current_user]=lambda: selected['user']
    try:
        with TestClient(app, base_url='http://localhost') as client:
            path='/api/v1/admin/workflow/dead-letters'
            response=client.get(path)
            assert response.status_code==403
            response=client.post(f'{path}/{event.id}/requeue',json={'reason':'Fixed the stalled workflow'})
            assert response.status_code==403
            selected['user']=admin
            assert any(row['id']==str(event.id) for row in client.get(path).json())
            response=client.post(f'{path}/{event.id}/requeue',json={'reason':'Fixed the stalled workflow'})
            assert response.status_code==200, response.text
            assert client.post(f'{path}/{event.id}/requeue',json={'reason':'Fixed the stalled workflow'}).status_code==409
    finally:
        app.dependency_overrides.pop(get_db,None)
        app.dependency_overrides.pop(get_current_user,None)


def test_batch_recycling_sale_rejects_nonrecyclable_category(db):
    admin,user,org,fac,hospitals,records,proofs=seeded_sale(db)
    records[0].category.is_recyclable=False
    db.commit()
    with pytest.raises(HTTPException) as exc:
        record_sale(payload(org,records),user,db)
    assert exc.value.status_code==409


def test_completed_batch_that_becomes_invalid_blocks_payment(db):
    admin,user,org,fac,hospitals,records,proofs=seeded_sale(db)
    sale=record_sale(payload(org,records),user,db)
    proofs[0].processing_method='INCINERATION'
    db.commit()
    with pytest.raises(HTTPException) as exc:
        confirm_recycling_sale(sale['id'],VerifySale(bank_receipt_reference='receipt-00001'),admin,db)
    assert exc.value.status_code==409
    assert not db.scalars(select(Journal.id)).all()
