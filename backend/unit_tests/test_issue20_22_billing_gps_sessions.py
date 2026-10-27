"""Regression coverage for closed-cycle completeness, GPS provenance, and per-vehicle session uniqueness.

SQLite unit tests cover partial index behavior; deployment still needs real PostgreSQL migration/concurrency testing.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models  # noqa
from app.core.db import Base
from app.core.config import Settings
from app.models.business import Organization, BillingContract, ContractRate, HospitalInvoice, InvoiceLine, InvoiceAdjustment, Journal, PaymentIntent
from app.models.hospital_profile import HospitalProfile
from app.models.waste_category import WasteCategory
from app.models.waste_record import WasteRecord
from app.models.waste_event import WasteEvent
from app.models.processing_record import ProcessingRecord
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.tracking import TrackingSession, TrackingSessionStatus, TrackingLocation, LocationSource
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.pickup_request import PickupRequest, PickupRequestItem
from app.models.collection_proof import CollectionProof
from app.models.roles import UserRole
from app.models.waste_enums import WasteStatus, WasteUnit, WasteEventType, PickupPriority, PickupStatus
from app.services.business_finance import issue_invoice
from app.services.tracking_service import TrackingService, ActiveTrackingSessionExistsError
from app.schemas.tracking import TrackingSessionCreate
from app.api.tracking import role_tracking_overview
from unit_tests.test_issue12_13_gps_realtime import setup_route


@pytest.fixture
def db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def finance_setup(db):
    u=User(email='bill@example.test',full_name='Hospital',hashed_password='x',role=UserRole.HOSPITAL)
    db.add(u);db.flush()
    org=Organization(name='Hospital org',org_type='HOSPITAL',owner_user_id=u.id,status='verified')
    db.add(org);db.flush()
    profile=HospitalProfile(user_id=u.id,organization_id=org.id,name='Hospital',
        registration_number='R001',contact_person='Team',phone='12345',address_line='X',
        city='Khulna',region='Khulna',postal_code='9000')
    category=WasteCategory(code='GEN',name='General')
    contract=BillingContract(hospital_org_id=org.id,billing_anchor_local=date(2026,1,1),
        cycle_days=15,due_days=15,active=True)
    db.add_all([profile,category,contract]);db.flush()
    return org,profile,category,contract


def add_completed(db,profile,category,code='W-1',quantity=Decimal('10')):
    # A completion event in the first closed 15-day cycle, independent of the
    # current wall clock (old closed periods must always be allowed).
    when=datetime(2026,1,5,tzinfo=timezone.utc)
    record=WasteRecord(waste_code=code,hospital_id=profile.id,category_id=category.id,
        reported_by=profile.user_id,generated_at=when,quantity=quantity,unit=WasteUnit.KG,
        received_quantity=quantity,received_at=when,status=WasteStatus.COMPLETED)
    db.add(record);db.flush()
    db.add(WasteEvent(waste_record_id=record.id,event_type=WasteEventType.COMPLETED,
        status_snapshot=WasteStatus.COMPLETED,created_at=when,quantity=quantity))
    db.flush()
    return record


def add_proof_rate(db,category,contract,record):
    # No facility FK needed for the rate-only check; processing proof fixture
    # is created separately where needed.
    db.add(ContractRate(contract_id=contract.id,category_id=category.id,
        effective_from=date(2026,1,1),collection_rate=Decimal('10'),
        treatment_rate=Decimal('5'),platform_rate=Decimal('1')))
    db.flush()


def add_proof(db,record):
    facility_user=User(email=f'facility-{record.waste_code}@test.invalid',full_name='Facility',hashed_password='x',role=UserRole.FACILITY)
    driver=User(email=f'driver-{record.waste_code}@test.invalid',full_name='Driver',hashed_password='x',role=UserRole.COLLECTOR)
    db.add_all([facility_user,driver]);db.flush()
    facility_org=Organization(name=f'Facility {record.waste_code}',org_type='TREATMENT_FACILITY',owner_user_id=facility_user.id,status='verified')
    company_org=Organization(name=f'Collector {record.waste_code}',org_type='COLLECTION_COMPANY',owner_user_id=driver.id,status='verified')
    db.add_all([facility_org,company_org]);db.flush()
    f=TreatmentFacilityProfile(user_id=facility_user.id,organization_id=facility_org.id,name='Facility',registration_number=f'F-{record.waste_code}',
        contact_person='X',phone='12345',address_line='X',city='Khulna',region='Khulna',postal_code='9000',capacity_kg=Decimal('200'))
    vehicle=Vehicle(vehicle_code=f'TEST-{record.waste_code}',assigned_collector_id=driver.id,
        organization_id=company_org.id,capacity_kg=Decimal('200'))
    db.add_all([f,vehicle]);db.flush()
    pickup=PickupRequest(hospital_id=record.hospital_id,requested_by=record.reported_by,
        priority=PickupPriority.NORMAL,status=PickupStatus.COMPLETED,
        assigned_vehicle_id=vehicle.id,assigned_collector_id=driver.id)
    db.add(pickup);db.flush()
    db.add_all([
        PickupRequestItem(pickup_request_id=pickup.id,waste_record_id=record.id),
        CollectionProof(pickup_id=pickup.id,verified_by=driver.id,accepted_weight_kg=record.quantity,
            packaging_condition='sealed',acknowledgement='accepted'),
        ProcessingRecord(waste_record_id=record.id,facility_id=f.id,
            processing_method='INCINERATION',completed_at=datetime(2026,1,5,tzinfo=timezone.utc)),
    ])
    db.flush()
    return company_org, facility_org


def test_incomplete_completed_batch_blocks_final_invoice_without_any_journal(db):
    _,hp,category,contract=finance_setup(db)
    record=add_completed(db,hp,category)
    with pytest.raises(ValueError, match='missing completed processing proof'):
        issue_invoice(db,contract,0)
    assert db.scalar(select(HospitalInvoice.id)) is None
    assert db.scalar(select(Journal.id)) is None
    add_proof(db,record)
    with pytest.raises(ValueError, match='missing effective category rate'):
        issue_invoice(db,contract,0)
    add_proof_rate(db,category,contract,record)
    invoice=issue_invoice(db,contract,0)
    assert invoice.gross_bdt == Decimal('160.00')
    assert invoice.due_bdt == Decimal('160.00')
    assert db.scalar(select(InvoiceLine).where(InvoiceLine.waste_record_id==record.id)).invoice_id == invoice.id
    assert issue_invoice(db,contract,0).id == invoice.id


def test_incomplete_weight_blocks_issue_even_if_proof_and_rate_exist(db):
    _,hp,category,contract=finance_setup(db)
    record=add_completed(db,hp,category)
    add_proof(db,record);add_proof_rate(db,category,contract,record)
    record.received_quantity=None
    db.flush()
    with pytest.raises(ValueError, match='missing verified kg'):
        issue_invoice(db,contract,0)
    assert db.scalar(select(HospitalInvoice)) is None


def test_unpaid_legacy_invoice_gets_audited_idempotent_adjustment(db):
    _,hp,category,contract=finance_setup(db)
    empty=issue_invoice(db,contract,0)
    record=add_completed(db,hp,category)
    add_proof(db,record);add_proof_rate(db,category,contract,record)
    corrected=issue_invoice(db,contract,0)
    assert corrected.id == empty.id
    assert corrected.gross_bdt==Decimal('160.00')
    assert corrected.due_bdt==Decimal('160.00')
    audit=db.scalar(select(InvoiceAdjustment).where(InvoiceAdjustment.waste_record_id==record.id))
    assert audit.invoice_id==corrected.id and audit.total_bdt==Decimal('160.00')
    assert len(list(db.scalars(select(Journal))))==1
    assert len(list(db.scalars(select(InvoiceLine))))==1
    # A repeat issuance cannot double-bill the same batch.
    assert issue_invoice(db,contract,0).gross_bdt==Decimal('160.00')
    assert len(list(db.scalars(select(InvoiceAdjustment))))==1


def test_partially_paid_invoice_cannot_be_increased_by_late_batch(db):
    _,hp,category,contract=finance_setup(db)
    prior=issue_invoice(db,contract,0)
    prior.paid_bdt=Decimal('2.00');prior.state='partially_paid';db.commit()
    record=add_completed(db,hp,category)
    add_proof(db,record);add_proof_rate(db,category,contract,record)
    with pytest.raises(ValueError, match='Paid or partially paid'):
        issue_invoice(db,contract,0)
    assert db.scalar(select(InvoiceAdjustment)) is None


def test_existing_checkout_blocks_adjustment(db):
    _,hp,category,contract=finance_setup(db)
    old=issue_invoice(db,contract,0)
    from app.models.user import User
    payer=db.scalar(select(User).where(User.email=='bill@example.test'))
    db.add(PaymentIntent(payer_user_id=payer.id,organization_id=old.hospital_org_id,
        target_kind='invoice',target_id=old.id,idempotency_key='first',merchant_reference='first',
        gateway='mock',mode='mock',requested_channel='card',amount_bdt=Decimal('2'),
        state='created',callback_nonce='nonce'))
    db.commit()
    record=add_completed(db,hp,category)
    add_proof(db,record);add_proof_rate(db,category,contract,record)
    with pytest.raises(ValueError, match='checkout/payment intent'):
        issue_invoice(db,contract,0)
    assert db.scalar(select(InvoiceAdjustment)) is None


def test_partial_unique_index_blocks_second_active_session_and_releases_on_completion(db):
    driver=User(email='driver@invalid.test',full_name='Driver',hashed_password='x',role=UserRole.COLLECTOR)
    db.add(driver);db.flush()
    vehicle=Vehicle(vehicle_code='UNIT-22',assigned_collector_id=driver.id,capacity_kg=Decimal('200'))
    db.add(vehicle);db.flush()
    first=TrackingSession(vehicle_id=vehicle.id,status=TrackingSessionStatus.ACTIVE)
    db.add(first);db.commit()
    duplicate=TrackingSession(vehicle_id=vehicle.id,status=TrackingSessionStatus.CREATED)
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    first=db.get(TrackingSession,first.id)
    first.status=TrackingSessionStatus.COMPLETED
    db.commit()
    second=TrackingSession(vehicle_id=vehicle.id,status=TrackingSessionStatus.PAUSED)
    db.add(second);db.commit()
    assert second.id is not None


def test_session_creation_raises_existing_conflict(db):
    driver=User(email='collector@invalid.test',full_name='Driver',hashed_password='x',role=UserRole.COLLECTOR)
    db.add(driver);db.flush()
    vehicle=Vehicle(vehicle_code='UNIT-22-B',assigned_collector_id=driver.id,capacity_kg=Decimal('200'))
    db.add(vehicle);db.commit()
    svc=TrackingService(db,Settings(database_url='sqlite+pysqlite:///:memory:'))
    first=svc.create_session(user=driver,data=TrackingSessionCreate(vehicle_id=vehicle.id))
    with pytest.raises(ActiveTrackingSessionExistsError):
        svc.create_session(user=driver,data=TrackingSessionCreate(vehicle_id=vehicle.id))
    assert first.id is not None


def test_role_overview_exposes_gps_trust_and_anomaly():
    engine,db,driver,vehicle,session,stop=setup_route()
    try:
        admin=User(email='gpsadmin@invalid.test',full_name='Admin',hashed_password='x',role=UserRole.ADMIN)
        db.add(admin);db.flush()
        from app.models.route import Route
        route=db.get(Route,session.current_route_id)
        route.tracking_session_id=session.id
        db.flush()
        db.add(TrackingLocation(tracking_session_id=session.id,vehicle_id=vehicle.id,
            latitude=Decimal('22.81'),longitude=Decimal('89.55'),timestamp=datetime.now(timezone.utc),
            source=LocationSource.MOBILE_APP,provenance_verified=False))
        db.commit()
        result=role_tracking_overview(current_user=admin,db=db)
        location=next(r['location'] for r in result['vehicles'] if r['vehicle']['id']==str(vehicle.id))
        assert location['provenance_verified'] is False
        assert location['anomaly_type'] is None
        assert location['source']=='mobile_app'
    finally: db.close();engine.dispose()
