"""Issue 8: durable worker organizations are verified against record ownership.

These tests use in-memory SQLite and isolated stage stubs. They check the
actual worker security/context wrapper and outbox persistence, not Postgres.
"""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app import models  # noqa
from app.core.db import Base
from app.models.business import Organization, OrganizationMember, EventOutbox
from app.models.hospital_profile import HospitalProfile
from app.models.user import User
from app.models.roles import UserRole
from app.models.waste_category import WasteCategory
from app.models.waste_record import WasteRecord
from app.models.waste_enums import WasteStatus, WasteUnit
from app.services.organization_context import selected_org_id, select_organization, reset_organization
from app.services.workflow_orchestrator import process_one, enqueue_report
from app.services import workflow_orchestrator
from app.services.waste_service import WasteService
from app.schemas.waste import WasteRecordCreate

@pytest.fixture
def tenant_db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        actor = User(email='multi@example.test', full_name='Multi', hashed_password='x', role=UserRole.HOSPITAL)
        other = User(email='other@example.test', full_name='Other', hashed_password='x', role=UserRole.HOSPITAL)
        db.add_all([actor, other]); db.flush()
        organizations = []
        profiles = []
        for i in range(2):
            org = Organization(name=f'Clinic {i}', org_type='HOSPITAL', owner_user_id=actor.id, status='verified')
            db.add(org); db.flush()
            db.add(OrganizationMember(organization_id=org.id, user_id=actor.id, member_role='owner', active=True))
            hp = HospitalProfile(user_id=actor.id, organization_id=org.id, name=f'Clinic {i}',
                registration_number=f'reg-{i}', contact_person='Test', phone='111',
                address_line='Road', city='Khulna', region='Khulna', postal_code='9000')
            db.add(hp); db.flush()
            organizations.append(org); profiles.append(hp)
        cat = WasteCategory(code='GENERAL', name='General')
        db.add(cat); db.flush()
        records = []
        for i, hp in enumerate(profiles):
            rec = WasteRecord(waste_code=f'MW-{i}', hospital_id=hp.id, category_id=cat.id,
                reported_by=actor.id, quantity=5, unit=WasteUnit.KG,
                generated_at=datetime.now(timezone.utc), status=WasteStatus.REPORTED)
            db.add(rec); db.flush(); records.append(rec)
        db.commit()
        yield db, actor, other, organizations, profiles, cat, records
    engine.dispose()


def envelope(db, rec, actor, org=None, hospital=None):
    payload = {'record_id': str(rec.id), 'user_id': str(actor.id)}
    if org is not ...:
        payload['organization_id'] = str(org) if org is not None else None
    if hospital is not None:
        payload['hospital_id'] = str(hospital)
    event = EventOutbox(dedupe_key=f'waste-report:{rec.id}', topic='waste.report.progress', payload=payload)
    db.add(event); db.commit(); return event


def test_multi_org_worker_restores_tenant_after_each_report(tenant_db, monkeypatch):
    db, actor, _, orgs, _, _, records = tenant_db
    seen = []
    def stage(db_arg, rec, user_id):
        assert user_id == actor.id
        # The real service must be able to locate the right company profile,
        # even though this user belongs to two separate hospitals.
        scoped = WasteService(db_arg).get_record(user_id=user_id, record_id=rec.id)
        assert scoped.id == rec.id
        seen.append(selected_org_id())
        return 'completed'
    monkeypatch.setattr(workflow_orchestrator, '_process_verified_report', stage)
    first = envelope(db, records[0], actor, orgs[0].id, records[0].hospital_id)
    assert process_one(db, first) == 'completed'
    second = envelope(db, records[1], actor, orgs[1].id, records[1].hospital_id)
    assert process_one(db, second) == 'completed'
    assert seen == [orgs[0].id, orgs[1].id]
    assert selected_org_id() is None


def test_legacy_envelope_derives_org_from_immutable_record(tenant_db, monkeypatch):
    db, actor, _, orgs, _, _, records = tenant_db
    monkeypatch.setattr(workflow_orchestrator, '_process_verified_report', lambda db, rec, user: ('completed' if selected_org_id() == orgs[1].id else 'wrong'))
    event = envelope(db, records[1], actor, ...)
    assert process_one(db, event) == 'completed'
    assert selected_org_id() is None


def test_cross_tenant_or_forged_envelope_does_not_run(tenant_db, monkeypatch):
    db, actor, other, orgs, _, _, records = tenant_db
    called = []
    monkeypatch.setattr(workflow_orchestrator, '_process_verified_report', lambda *args: called.append(True))
    event = envelope(db, records[0], actor, orgs[1].id)
    assert process_one(db, event) == 'manual_review'
    event.payload = {'record_id': str(records[0].id), 'user_id': str(other.id)}
    db.commit()
    assert process_one(db, event) == 'manual_review'
    assert not called
    assert selected_org_id() is None


def test_removed_membership_blocks_existing_queued_job(tenant_db, monkeypatch):
    db, actor, _, orgs, _, _, records = tenant_db
    event = envelope(db, records[0], actor, orgs[0].id)
    member = db.scalar(select(OrganizationMember).where(OrganizationMember.user_id==actor.id,
        OrganizationMember.organization_id==orgs[0].id))
    member.active = False
    db.commit()
    with patch.object(workflow_orchestrator, '_process_verified_report') as stage:
        assert process_one(db, event) == 'manual_review'
        stage.assert_not_called()
    assert selected_org_id() is None


def test_worker_exception_always_resets_context(tenant_db, monkeypatch):
    db, actor, _, orgs, _, _, records = tenant_db
    event = envelope(db, records[0], actor, orgs[0].id)
    def boom(*args):
        assert selected_org_id() == orgs[0].id
        raise RuntimeError('broken stage')
    monkeypatch.setattr(workflow_orchestrator, '_process_verified_report', boom)
    with pytest.raises(RuntimeError, match='broken stage'):
        process_one(db, event)
    assert selected_org_id() is None


def test_enqueue_existing_and_retry_preserves_verified_tenant(tenant_db):
    db, actor, other, orgs, _, _, records = tenant_db
    selected = select_organization(str(orgs[1].id))
    try:
        enqueue_report(db, record_id=records[1].id, user_id=actor.id)
        event = db.scalar(select(EventOutbox).where(EventOutbox.dedupe_key==f'waste-report:{records[1].id}'))
        assert event.payload['organization_id'] == str(orgs[1].id)
        assert event.payload['hospital_id'] == str(records[1].hospital_id)
        event.topic = 'waste.report.manual_review'; event.delivered_at=datetime.now(timezone.utc)
        db.commit()
        enqueue_report(db, record_id=records[1].id, user_id=actor.id)
        db.refresh(event)
        assert event.topic == 'waste.report.progress' and event.delivered_at is None
        assert event.payload['organization_id'] == str(orgs[1].id)
    finally:
        reset_organization(selected)
    token = select_organization(str(orgs[0].id))
    try:
        with pytest.raises(Exception):
            enqueue_report(db, record_id=records[1].id, user_id=actor.id)
    finally:
        reset_organization(token)
    assert selected_org_id() is None


def test_enqueue_denies_other_user_and_does_not_create_outbox(tenant_db):
    db, actor, other, orgs, _, _, records = tenant_db
    token = select_organization(str(orgs[0].id))
    try:
        with pytest.raises(Exception):
            enqueue_report(db, record_id=records[0].id, user_id=other.id)
    finally:
        reset_organization(token)
    assert not db.scalar(select(EventOutbox).where(EventOutbox.dedupe_key==f'waste-report:{records[0].id}'))


def test_atomic_report_envelope_uses_server_profile(tenant_db, monkeypatch):
    db, actor, _, orgs, _, category, _ = tenant_db
    token = select_organization(str(orgs[0].id))
    try:
        service = WasteService(db)
        monkeypatch.setattr(service.records, 'next_sequence_value', lambda: 519)
        created = service.create_record(user_id=actor.id, data=WasteRecordCreate(
            category_id=category.id, quantity=3, unit=WasteUnit.KG,
            generated_at=datetime.now(timezone.utc), description='Routine items'))
        event = db.scalar(select(EventOutbox).where(EventOutbox.dedupe_key==f'waste-report:{created.id}'))
        assert event.payload['hospital_id'] == str(created.hospital_id)
        assert event.payload['organization_id'] == str(orgs[0].id)
    finally:
        reset_organization(token)


def test_disabled_user_does_not_run_queued_job(tenant_db, monkeypatch):
    db, actor, _, orgs, _, _, records = tenant_db
    event = envelope(db, records[0], actor, orgs[0].id)
    actor.is_active = False
    db.commit()
    with patch.object(workflow_orchestrator, '_process_verified_report') as stage:
        assert process_one(db, event) == 'manual_review'
        stage.assert_not_called()
    assert selected_org_id() is None


def test_real_batch_runs_two_tenants_without_context_leakage(tenant_db, monkeypatch):
    db, actor, _, orgs, _, _, records = tenant_db
    seen = []
    def stage(session, record, user_id):
        seen.append((record.id, selected_org_id()))
        assert WasteService(session).get_record(user_id=user_id, record_id=record.id).id == record.id
        return 'completed'
    monkeypatch.setattr(workflow_orchestrator, '_process_verified_report', stage)
    for rec, org in zip(records, orgs):
        envelope(db, rec, actor, org.id, rec.hospital_id)
    assert workflow_orchestrator.run_workflow_batch(db, limit=10) == {
        'completed': 2, 'manual_review': 0, 'retry': 0,
    }
    assert seen == [(records[0].id, orgs[0].id), (records[1].id, orgs[1].id)]
    assert selected_org_id() is None


def test_envelope_wrong_hospital_id_is_manual_review(tenant_db, monkeypatch):
    db, actor, _, orgs, _, _, records = tenant_db
    event = envelope(db, records[0], actor, orgs[0].id, records[1].hospital_id)
    with patch.object(workflow_orchestrator, '_process_verified_report') as stage:
        assert process_one(db, event) == 'manual_review'
        stage.assert_not_called()
