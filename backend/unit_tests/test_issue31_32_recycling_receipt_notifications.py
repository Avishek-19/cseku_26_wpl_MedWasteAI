"""Regression tests for hospital-scoped recycling journals and reliable receipt notices.

These use SQLite for isolation; PostgreSQL worker concurrency still needs an
integration environment. No real notifications, payments or GPS are sent.
"""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from app.models.business import EventOutbox, Journal, JournalLine
from app.models.notification import Notification
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.hospital_profile import HospitalProfile
from app.models.matching_record import MatchingRecord
from app.models.waste_enums import DestinationType, WasteStatus
from app.models.roles import UserRole
from app.services.receiving_service import ReceivingService
from app.services.workflow_orchestrator import run_workflow_batch
from app.services import workflow_orchestrator
from app.services.business_finance import record_recycling_distribution
from unit_tests.test_issue14_15_workflow_recycling import (
    db, seeded_sale, payload, new_user, new_org,
)
from unit_tests.test_issue1_pickup_delivery_completion import setup_route


def _distribution(db, weights=(Decimal('4.50'), Decimal('5.50')),
                  proceeds=Decimal('2000.00'), costs=Decimal('500.00')):
    admin, user, facility_org, facility, hospitals, records, processing = seeded_sale(db, weights)
    from app.models.business import RecyclingSale, RecyclingSaleLot
    sale = RecyclingSale(facility_org_id=facility_org.id, source_reference=uuid4().hex,
        clearance_reference='clearance', buyer_invoice_ref='invoice',
        proceeds_bdt=proceeds, approved_costs_bdt=costs, sale_payment_verified=True,
        approved_by=admin.id)
    db.add(sale); db.flush()
    for record, hospital, weight in zip(records, hospitals, weights):
        db.add(RecyclingSaleLot(sale_id=sale.id, waste_record_id=record.id,
                                hospital_org_id=hospital.id, contribution_kg=weight))
    db.commit()
    return sale, hospitals


def test_distribution_credits_hospital_ledger_lines_separately_and_balances(db):
    sale, hospitals = _distribution(db)
    allocations = record_recycling_distribution(db, sale)
    journal = db.scalar(select(Journal).where(Journal.unique_event == f'recycle_distribution:{sale.id}'))
    lines = list(db.scalars(select(JournalLine).where(JournalLine.journal_id == journal.id)))
    hospital_lines = [line for line in lines if line.account == 'hospital_recycling_credit_liability']
    assert len(hospital_lines) == 2
    assert {line.organization_id: line.amount_bdt for line in hospital_lines} == {
        hospitals[0].id: Decimal('405.00'), hospitals[1].id: Decimal('495.00')}
    assert all(line.side == 'credit' and line.organization_id is not None for line in hospital_lines)
    assert sum((line.amount_bdt for line in lines if line.side == 'debit'), Decimal(0)) == sum(
        (line.amount_bdt for line in lines if line.side == 'credit'), Decimal(0))
    assert {x.hospital_org_id: x.hospital_credit_bdt for x in allocations} == {
        line.organization_id: line.amount_bdt for line in hospital_lines}


def test_small_cent_distribution_rounds_without_anonymous_or_zero_lines(db):
    sale, hospitals = _distribution(db, weights=(Decimal('1.0'), Decimal('1.0')),
                                    proceeds=Decimal('0.01'), costs=Decimal('0.00'))
    allocations = record_recycling_distribution(db, sale)
    journal = db.scalar(select(Journal).where(Journal.unique_event == f'recycle_distribution:{sale.id}'))
    lines = list(db.scalars(select(JournalLine).where(JournalLine.journal_id == journal.id)))
    assigned = [line for line in lines if line.account == 'hospital_recycling_credit_liability']
    assert sum((x.amount_bdt for x in assigned), Decimal(0)) == Decimal('0.01')
    assert len(assigned) == 1  # last hospital gets the residual cent
    assert assigned[0].organization_id in {h.id for h in hospitals}
    assert sum((line.amount_bdt for line in lines if line.side == 'debit'), Decimal(0)) == sum(
        (line.amount_bdt for line in lines if line.side == 'credit'), Decimal(0))
    assert sum((x.hospital_credit_bdt for x in allocations), Decimal(0)) == Decimal('0.01')


def _receipt_fixture(db, monkeypatch):
    from app.realtime.tracking_manager import tracking_manager
    import app.services.organization_eligibility as eligibility
    from app.models.waste_record import WasteRecord

    route, vehicle, pickups, records, _, _ = setup_route(db)
    rec = records[0]
    hospital_user = new_user(db, 'notice-hospital-' + uuid4().hex[:6], UserRole.HOSPITAL)
    hospital = HospitalProfile(id=pickups[0].hospital_id, user_id=hospital_user.id,
        name='Hospital for notification', registration_number='h01',
        contact_person='test', phone='1', address_line='address',city='Khulna',
        region='Khulna',postal_code='9000')
    facility_user = new_user(db, 'notice-facility-' + uuid4().hex[:6], UserRole.FACILITY)
    facility = TreatmentFacilityProfile(user_id=facility_user.id,
        name='Real facility', registration_number='f01', contact_person='test',
        phone='1',address_line='facility addr',city='Khulna',region='Khulna',
        postal_code='9000',capacity_kg=Decimal('100'),current_utilization_kg=Decimal(0))
    db.add_all([hospital, facility]); db.flush()
    match = MatchingRecord(waste_record_id=rec.id, destination_type=DestinationType.WASTE_PROCESSING_FACILITY,
        candidates=[], explanation='test', confirmed_facility_id=facility.id, is_confirmed=True)
    db.add(match);db.commit()
    receiving = ReceivingService(db)
    monkeypatch.setattr(receiving, '_own_profile', lambda *, user_id: facility)
    monkeypatch.setattr(receiving.matches, 'get_confirmed_for_record', lambda _: match)
    monkeypatch.setattr(eligibility, 'eligible_facility', lambda *args: True)
    monkeypatch.setattr(eligibility, 'can_profile_action', lambda *args: True)
    monkeypatch.setattr(tracking_manager, 'broadcast_from_sync', lambda *args: None)
    return receiving, rec, hospital, facility, facility_user


def _receive(db, monkeypatch):
    receiving, record, hospital, facility, actor = _receipt_fixture(db, monkeypatch)
    result = receiving.confirm_receipt(user_id=actor.id, record_id=record.id,
                                       received_quantity=Decimal('1.00'))
    assert result.waste_record_id == record.id
    return record, hospital, facility


def test_receipt_commits_without_synchronous_notification_and_worker_delivers(db, monkeypatch):
    record, hospital, facility = _receive(db, monkeypatch)
    row = db.scalar(select(EventOutbox).where(EventOutbox.dedupe_key ==
        f'facility-receipt-notification:{record.id}'))
    assert row is not None and row.delivered_at is None
    assert row.topic == 'notification.facility.received'
    assert db.scalar(select(Notification.id)) is None
    assert run_workflow_batch(db) == {'completed': 1, 'manual_review': 0, 'retry': 0}
    db.refresh(row)
    assert row.delivered_at is not None
    note = db.scalar(select(Notification).where(Notification.waste_record_id == record.id))
    assert note.user_id == hospital.user_id and facility.name in note.body
    assert run_workflow_batch(db)['completed'] == 0
    assert db.scalar(select(func.count(Notification.id))) == 1


def test_notification_failure_retries_independently_of_committed_receipt(db, monkeypatch):
    record, hospital, facility = _receive(db, monkeypatch)
    row = db.scalar(select(EventOutbox).where(EventOutbox.dedupe_key ==
        f'facility-receipt-notification:{record.id}'))
    real = workflow_orchestrator.process_receipt_notification
    monkeypatch.setattr(workflow_orchestrator, 'process_receipt_notification',
                        lambda *_: (_ for _ in ()).throw(RuntimeError('notification storage offline')))
    assert run_workflow_batch(db)['retry'] == 1
    db.refresh(row)
    assert row.attempts == 1 and row.delivered_at is None
    db.expire_all()
    assert db.get(type(record), record.id).status == WasteStatus.DESTINATION_RECEIVED
    assert db.scalar(select(Notification.id)) is None
    monkeypatch.setattr(workflow_orchestrator, 'process_receipt_notification', real)
    assert run_workflow_batch(db)['completed'] == 1
    db.refresh(row)
    assert row.delivered_at is not None
    assert db.scalar(select(func.count(Notification.id))) == 1


def test_replayed_notification_job_does_not_create_second_message(db, monkeypatch):
    record, hospital, facility = _receive(db, monkeypatch)
    assert run_workflow_batch(db)['completed'] == 1
    row = db.scalar(select(EventOutbox).where(EventOutbox.dedupe_key ==
        f'facility-receipt-notification:{record.id}'))
    # Simulate an audited manual requeue of an acknowledged outbox event.
    row.delivered_at = None; db.commit()
    assert run_workflow_batch(db)['completed'] == 1
    assert db.scalar(select(func.count(Notification.id))) == 1


def test_failed_notification_is_dead_lettered_and_admin_can_requeue(db, monkeypatch):
    from app.api.admin import DeadLetterRetryRequest, list_workflow_dead_letters, requeue_workflow_dead_letter
    record, hospital, facility = _receive(db, monkeypatch)
    row = db.scalar(select(EventOutbox).where(EventOutbox.dedupe_key ==
        f'facility-receipt-notification:{record.id}'))
    original = workflow_orchestrator.process_receipt_notification
    monkeypatch.setattr(workflow_orchestrator, 'process_receipt_notification',
                        lambda *_: (_ for _ in ()).throw(RuntimeError('storage offline')))
    for _ in range(5): assert run_workflow_batch(db)['retry'] == 1
    db.refresh(row)
    assert row.topic == 'notification.facility.received.dead_letter'
    assert row.attempts == 5 and row.last_error == 'RuntimeError'
    admin = new_user(db, 'requeue-admin-' + uuid4().hex[:6], UserRole.ADMIN)
    db.commit()
    assert any(event['id'] == str(row.id) for event in list_workflow_dead_letters(100, admin, db))
    result = requeue_workflow_dead_letter(row.id,
        DeadLetterRetryRequest(reason='Recovered notification database'), admin, db)
    assert result['status'] == 'queued'
    db.refresh(row)
    assert row.topic == 'notification.facility.received' and row.attempts == 0
    monkeypatch.setattr(workflow_orchestrator, 'process_receipt_notification', original)
    assert run_workflow_batch(db)['completed'] == 1
    assert db.scalar(select(func.count(Notification.id))) == 1


def test_malformed_notification_envelope_never_creates_notification(db):
    row = EventOutbox(dedupe_key='bad:'+uuid4().hex,topic='notification.facility.received',
        payload={'record_id': str(uuid4()), 'facility_id': 'bogus'})
    db.add(row);db.commit()
    assert run_workflow_batch(db)['retry'] == 1
    assert db.scalar(select(Notification.id)) is None


def test_notification_insert_and_ack_both_roll_back_when_worker_fails(db, monkeypatch):
    record, hospital, facility = _receive(db, monkeypatch)
    row = db.scalar(select(EventOutbox).where(EventOutbox.dedupe_key ==
        f'facility-receipt-notification:{record.id}'))
    original = workflow_orchestrator.process_receipt_notification

    def fail_after_staging(database, event):
        original(database, event)
        database.flush()  # Notification INSERT happens, but is not committed
        raise RuntimeError('worker failed after staging notification')

    monkeypatch.setattr(workflow_orchestrator, 'process_receipt_notification', fail_after_staging)
    assert run_workflow_batch(db)['retry'] == 1
    db.expire_all()
    assert db.scalar(select(Notification.id)) is None
    assert db.get(EventOutbox, row.id).delivered_at is None
    assert db.get(type(record), record.id).status == WasteStatus.DESTINATION_RECEIVED
    monkeypatch.setattr(workflow_orchestrator, 'process_receipt_notification', original)
    assert run_workflow_batch(db)['completed'] == 1
    assert db.scalar(select(func.count(Notification.id))) == 1


def test_receipt_commit_failure_rolls_back_notification_intent_together(db, monkeypatch):
    receiving, record, hospital, facility, actor = _receipt_fixture(db, monkeypatch)
    original_commit = db.commit

    def fail_commit():
        raise RuntimeError('receipt database unavailable')

    monkeypatch.setattr(db, 'commit', fail_commit)
    with pytest.raises(RuntimeError, match='receipt database unavailable'):
        receiving.confirm_receipt(user_id=actor.id, record_id=record.id,
                                  received_quantity=Decimal('1.00'))
    monkeypatch.setattr(db, 'commit', original_commit)
    db.rollback()
    db.expire_all()
    assert db.get(type(record), record.id).status == WasteStatus.IN_TRANSIT
    assert db.scalar(select(EventOutbox.id).where(
        EventOutbox.dedupe_key == f'facility-receipt-notification:{record.id}')) is None
    assert db.scalar(select(Notification.id)) is None
