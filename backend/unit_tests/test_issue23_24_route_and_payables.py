"""Issue 23/24: route/session lifecycle and per-organization posted payables.

SQLite isolated coverage, not a substitute for PostgreSQL row-lock integration.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models.business import InvoiceAdjustment, Journal, JournalLine, ContractRate, Organization
from app.models.route import Route, RouteStatus
from app.models.tracking import TrackingSession, TrackingSessionStatus
from app.models.vehicle import Vehicle
from app.services.tracking_service import (
    TrackingService, ActiveRouteInProgressError, TrackingSessionAlreadyClosedError,
)
from app.services.business_finance import issue_invoice
from unit_tests.test_issue12_13_gps_realtime import setup_route
from unit_tests.test_issue20_22_billing_gps_sessions import (
    db, finance_setup, add_completed, add_proof, add_proof_rate,
)


def test_cannot_end_live_route_tracking():
    engine, session_db, driver, vehicle, tracking, stop = setup_route()
    try:
        service = TrackingService(session_db, Settings(database_url='sqlite+pysqlite:///:memory:'))
        with pytest.raises(ActiveRouteInProgressError, match='active delivery route'):
            service.complete_session(user=driver, session_id=tracking.id)
        session_db.refresh(tracking)
        assert tracking.status == TrackingSessionStatus.ACTIVE
        assert tracking.ended_at is None
        assert session_db.get(Route, tracking.current_route_id).status == RouteStatus.ACTIVE
    finally:
        session_db.close(); engine.dispose()


def test_active_vehicle_route_blocks_even_when_session_route_link_missing():
    engine, session_db, driver, vehicle, tracking, stop = setup_route()
    try:
        tracking.current_route_id = None
        session_db.commit()
        service = TrackingService(session_db, Settings(database_url='sqlite+pysqlite:///:memory:'))
        with pytest.raises(ActiveRouteInProgressError):
            service.complete_session(user=driver, session_id=tracking.id)
        assert tracking.status == TrackingSessionStatus.ACTIVE
    finally:
        session_db.close(); engine.dispose()


def test_terminal_route_allows_one_safe_session_completion():
    engine, session_db, driver, vehicle, tracking, stop = setup_route()
    try:
        route = session_db.get(Route, tracking.current_route_id)
        route.status = RouteStatus.COMPLETED
        session_db.commit()
        service = TrackingService(session_db, Settings(database_url='sqlite+pysqlite:///:memory:'))
        completed = service.complete_session(user=driver, session_id=tracking.id)
        assert completed.status == TrackingSessionStatus.COMPLETED
        assert completed.ended_at is not None
        assert completed.current_route_id is None
        assert service.complete_session(user=driver,session_id=tracking.id).id == tracking.id
    finally:
        session_db.close(); engine.dispose()


def test_cancelled_tracking_cannot_be_rebranded_completed():
    engine, session_db, driver, vehicle, tracking, stop = setup_route()
    try:
        route = session_db.get(Route, tracking.current_route_id)
        route.status = RouteStatus.CANCELLED
        tracking.status = TrackingSessionStatus.CANCELLED
        session_db.commit()
        svc = TrackingService(session_db,Settings(database_url='sqlite+pysqlite:///:memory:'))
        with pytest.raises(TrackingSessionAlreadyClosedError):
            svc.complete_session(user=driver,session_id=tracking.id)
        assert tracking.status == TrackingSessionStatus.CANCELLED
    finally:
        session_db.close(); engine.dispose()


def _postings(db, journal_id):
    return [(r.account, r.side, r.amount_bdt, r.organization_id) for r in
            db.scalars(select(JournalLine).where(JournalLine.journal_id == journal_id)).all()]


def test_multi_company_multi_facility_invoice_credits_each_operator(db):
    hospital,hp,category,contract=finance_setup(db)
    a = add_completed(db,hp,category,code='W-23-A',quantity=Decimal('10'))
    b = add_completed(db,hp,category,code='W-23-B',quantity=Decimal('20'))
    company_a, facility_a = add_proof(db,a)
    company_b, facility_b = add_proof(db,b)
    add_proof_rate(db,category,contract,a)
    invoice=issue_invoice(db,contract,0)
    entries=_postings(db,db.scalar(select(Journal.id).where(Journal.unique_event==f'invoice:{invoice.id}')))
    assert ('operator_collection_payable','credit',Decimal('100.00'),company_a.id) in entries
    assert ('operator_collection_payable','credit',Decimal('200.00'),company_b.id) in entries
    assert ('facility_treatment_payable','credit',Decimal('50.00'),facility_a.id) in entries
    assert ('facility_treatment_payable','credit',Decimal('100.00'),facility_b.id) in entries
    assert ('platform_service_revenue','credit',Decimal('30.00'),None) in entries
    assert ('hospital_receivable','debit',Decimal('480.00'),hospital.id) in entries
    assert not any(acc in ('operator_collection_payable','facility_treatment_payable') and org is None
                   for acc,_,_,org in entries)
    assert sum(v for _,side,v,_ in entries if side=='debit') == sum(v for _,side,v,_ in entries if side=='credit')


def test_late_invoice_adjustment_credits_the_original_service_parties(db):
    _, hp, category, contract = finance_setup(db)
    original = issue_invoice(db,contract,0)
    record=add_completed(db,hp,category,code='W-LATE')
    company, facility = add_proof(db,record)
    add_proof_rate(db,category,contract,record)
    updated=issue_invoice(db,contract,0)
    assert updated.id == original.id
    adjustment=db.scalar(select(InvoiceAdjustment).where(InvoiceAdjustment.waste_record_id==record.id))
    entries=_postings(db,db.scalar(select(Journal.id).where(Journal.unique_event==f'invoice_adjustment:{adjustment.id}')))
    assert ('operator_collection_payable','credit',Decimal('100.00'),company.id) in entries
    assert ('facility_treatment_payable','credit',Decimal('50.00'),facility.id) in entries
    assert issue_invoice(db,contract,0).gross_bdt == Decimal('160.00')
    assert db.query(Journal).count() == 1


def test_missing_collection_organization_blocks_invoice_without_posting(db):
    _, hp, category, contract = finance_setup(db)
    record=add_completed(db,hp,category,code='W-LEGACY')
    company, facility=add_proof(db,record)
    add_proof_rate(db,category,contract,record)
    company.org_type='HOSPITAL'  # invalid attribution, not a collection operator
    db.flush()
    with pytest.raises(ValueError,match='collection company organization'):
        issue_invoice(db,contract,0)
    assert db.scalar(select(Journal.id)) is None


def test_missing_facility_organization_blocks_invoice_without_posting(db):
    _, hp, category, contract = finance_setup(db)
    record=add_completed(db,hp,category,code='W-NOFAC')
    company, facility=add_proof(db,record)
    add_proof_rate(db,category,contract,record)
    facility.org_type='HOSPITAL'
    db.flush()
    with pytest.raises(ValueError,match='treatment facility organization'):
        issue_invoice(db,contract,0)
    assert db.scalar(select(Journal.id)) is None


def test_completion_endpoint_returns_conflict_for_active_delivery():
    import asyncio
    from fastapi import HTTPException
    from app.api.tracking import complete_tracking_session
    engine, session_db, driver, vehicle, tracking, stop = setup_route()
    try:
        with pytest.raises(HTTPException) as caught:
            asyncio.run(complete_tracking_session(
                session_id=tracking.id, current_user=driver, db=session_db
            ))
        assert caught.value.status_code == 409
        assert 'active delivery route' in str(caught.value.detail)
    finally:
        session_db.close(); engine.dispose()


def test_multiple_batches_same_operator_aggregate_in_one_ledger_credit(db):
    _,hp,category,contract=finance_setup(db)
    a=add_completed(db,hp,category,code='W-SAME-A',quantity=Decimal('10'))
    b=add_completed(db,hp,category,code='W-SAME-B',quantity=Decimal('20'))
    company_a,facility_a=add_proof(db,a)
    company_b,facility_b=add_proof(db,b)
    from app.models.pickup_request import PickupRequest, PickupRequestItem
    from app.models.processing_record import ProcessingRecord
    pickup=db.scalar(select(PickupRequest).join(PickupRequestItem,
        PickupRequestItem.pickup_request_id==PickupRequest.id).where(
        PickupRequestItem.waste_record_id==b.id))
    vehicle=db.get(Vehicle,pickup.assigned_vehicle_id)
    vehicle.organization_id=company_a.id
    processing=db.scalar(select(ProcessingRecord).where(ProcessingRecord.waste_record_id==b.id))
    from app.models.facility_profile import TreatmentFacilityProfile
    facility_a_profile=db.scalar(select(TreatmentFacilityProfile).where(
        TreatmentFacilityProfile.organization_id==facility_a.id))
    processing.facility_id=facility_a_profile.id
    add_proof_rate(db,category,contract,a)
    invoice=issue_invoice(db,contract,0)
    entries=_postings(db,db.scalar(select(Journal.id).where(Journal.unique_event==f'invoice:{invoice.id}')))
    assert [x for x in entries if x[0]=='operator_collection_payable'] == [
        ('operator_collection_payable','credit',Decimal('300.00'),company_a.id)]
    assert [x for x in entries if x[0]=='facility_treatment_payable'] == [
        ('facility_treatment_payable','credit',Decimal('150.00'),facility_a.id)]
