"""Fast SQLite smoke/regression checks for commercial safety changes.

PostgreSQL concurrency and full delivery E2E require a real PostgreSQL test DB.
"""
import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import models  # noqa
from app.core.db import Base
from app.core.config import Settings
from app.models.user import User
from app.models.roles import UserRole
from app.models.business import (Organization, OrganizationMember, OrganizationPermit,
                                 OrganizationInvitation, EventOutbox, BillingContract,
                                 HospitalInvoice)
from app.models.vehicle import Vehicle
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.hospital_profile import HospitalProfile
from app.models.audit_log import AuditLog
from app.models.waste_enums import VehicleStatus, WasteStatus
from app.schemas.vehicle import VehicleCreate, VehicleUpdate
from app.services.vehicle_service import VehicleService, VehicleConflictError
from app.services.organization_eligibility import (eligible_facility, can_manage_profile,
                                                    profile_organization)
from app.services.receiving_service import ReceivingService, DestinationArrivalRequiredError
from app.services.business_finance import issue_invoice
from app.services import workflow_orchestrator


@pytest.fixture
def db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def make_user(db, role, name):
    user = User(email=f'{name}@example.test', full_name=name, hashed_password='pw', role=role)
    db.add(user)
    db.flush()
    return user


def make_org(db, owner, org_type, status='verified'):
    org = Organization(name='Company '+owner.full_name, org_type=org_type, status=status,
                       owner_user_id=owner.id)
    db.add(org)
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=owner.id,
                              member_role='owner', active=True))
    db.add(OrganizationPermit(organization_id=org.id, permit_type='test authorization',
                              reference=str(uuid.uuid4()), approval_status='approved',
                              expires_on=date.today()+timedelta(days=90)))
    db.commit()
    return org


def make_facility(db, owner, org):
    row = TreatmentFacilityProfile(user_id=owner.id, organization_id=org.id,
        name='Test facility', registration_number='REG-1', contact_person='Officer',
        phone='01700000000', address_line='Street', city='Khulna', region='Khulna',
        postal_code='9000', capacity_kg=Decimal('500'),
        current_utilization_kg=Decimal('0'), is_verified=True,
        availability_status='available', processing_services=['INCINERATION'])
    db.add(row)
    db.commit()
    return row


def test_vehicle_requires_company_membership(db):
    driver = make_user(db, UserRole.COLLECTOR, 'driver-solo')
    with pytest.raises(VehicleConflictError, match='collection company'):
        VehicleService(db).create_vehicle(collector_id=driver.id,
            data=VehicleCreate(vehicle_code='X1', capacity_kg=Decimal('100')))


def test_vehicle_is_company_owned(db):
    driver = make_user(db, UserRole.COLLECTOR, 'driver-company')
    org = make_org(db, driver, 'COLLECTION_COMPANY')
    vehicle = VehicleService(db).create_vehicle(collector_id=driver.id,
        data=VehicleCreate(vehicle_code='X2', capacity_kg=Decimal('250'), organization_id=org.id))
    assert vehicle.organization_id == org.id
    assert vehicle.status == VehicleStatus.AVAILABLE


def test_vehicle_patch_rejects_unsafe_status_override():
    with pytest.raises(ValidationError):
        VehicleUpdate.model_validate({'status': 'available'})


def test_cannot_deactivate_reserved_vehicle(db):
    driver = make_user(db, UserRole.COLLECTOR, 'driver-reserved')
    org = make_org(db, driver, 'COLLECTION_COMPANY')
    vehicle = VehicleService(db).create_vehicle(collector_id=driver.id,
        data=VehicleCreate(vehicle_code='X3', capacity_kg=Decimal('250'), organization_id=org.id))
    vehicle.status = VehicleStatus.RESERVED
    db.commit()
    with pytest.raises(VehicleConflictError, match='reserved'):
        VehicleService(db).update_vehicle(collector_id=driver.id, vehicle_id=vehicle.id,
                                          data=VehicleUpdate(is_active=False))


def test_no_verified_facility_without_verified_company(db):
    user = make_user(db, UserRole.FACILITY, 'facility-owner')
    org = make_org(db, user, 'TREATMENT_FACILITY', status='pending')
    profile = make_facility(db, user, org)
    assert not eligible_facility(db, profile, need_capability='INCINERATION')
    org.status='verified'
    db.commit()
    assert eligible_facility(db, profile, need_capability='INCINERATION')
    assert not eligible_facility(db, profile, need_capability='AUTOCLAVE')


def test_expired_permit_blocks_facility(db):
    user = make_user(db, UserRole.FACILITY, 'expired-owner')
    org = make_org(db, user, 'TREATMENT_FACILITY')
    profile = make_facility(db, user, org)
    permit = db.scalar(select(OrganizationPermit).where(OrganizationPermit.organization_id==org.id))
    permit.expires_on=date.today()-timedelta(days=1)
    db.commit()
    assert not eligible_facility(db, profile)


def test_worker_cannot_change_organization_profile(db):
    owner = make_user(db, UserRole.FACILITY, 'owner-roles')
    member = make_user(db, UserRole.FACILITY, 'worker-roles')
    org = make_org(db, owner, 'TREATMENT_FACILITY')
    profile = make_facility(db, owner, org)
    db.add(OrganizationMember(organization_id=org.id,user_id=member.id,member_role='worker'))
    db.commit()
    assert can_manage_profile(db, profile, owner.id, 'TREATMENT_FACILITY')
    assert not can_manage_profile(db, profile, member.id, 'TREATMENT_FACILITY')


def test_receipt_rejected_without_destination_arrival(db):
    owner = make_user(db, UserRole.FACILITY, 'receipt-owner')
    org = make_org(db, owner, 'TREATMENT_FACILITY')
    profile = make_facility(db, owner, org)
    record_id = uuid.uuid4()
    service = ReceivingService(db)
    from app.models.waste_record import WasteRecord
    from app.models.waste_enums import WasteUnit
    from app.models.waste_category import WasteCategory
    hospital_owner = make_user(db, UserRole.HOSPITAL, 'receipt-hospital-owner')
    hospital = HospitalProfile(user_id=hospital_owner.id, name='Receipt hospital',
        registration_number='RCP-HOSP', contact_person='Staff', phone='01700000000',
        address_line='Hospital Road', city='Khulna', region='Khulna', postal_code='9000')
    category = WasteCategory(code='GENERAL', name='General', is_recyclable=False)
    db.add_all([hospital, category]); db.flush()
    db.add(WasteRecord(id=record_id, waste_code='MW-RECEIPT-TEST', hospital_id=hospital.id,
        category_id=category.id, quantity=Decimal('8'), unit=WasteUnit.KG,
        generated_at=datetime.now(timezone.utc), status=WasteStatus.IN_TRANSIT))
    db.commit()
    service.matches.get_confirmed_for_record = lambda rid: SimpleNamespace(confirmed_facility_id=profile.id)
    with pytest.raises(DestinationArrivalRequiredError):
        service.confirm_receipt(user_id=owner.id, record_id=record_id, received_quantity=Decimal('8'))


def test_revoked_invitation_can_be_renewed_and_tokens_hashed(db):
    pytest.importorskip('bcrypt', reason='bcrypt must be installed from backend requirements for FastAPI routes')
    from app.api.business import InviteCreate, invite_member, revoke_invitation, accept_invitation
    owner = make_user(db, UserRole.HOSPITAL, 'invite-owner')
    recipient = make_user(db, UserRole.HOSPITAL, 'invite-target')
    org = make_org(db, owner, 'HOSPITAL', status='pending')
    data = InviteCreate(email=recipient.email, member_role='worker')
    first = invite_member(org.id, data, owner, db)
    raw1 = first['token']
    entry = db.scalar(select(OrganizationInvitation).where(OrganizationInvitation.organization_id==org.id))
    assert entry.token == hashlib.sha256(raw1.encode()).hexdigest()
    assert entry.token != raw1
    revoke_invitation(org.id, entry.id, owner, db)
    second = invite_member(org.id, data, owner, db)
    assert raw1 != second['token']
    assert db.scalar(select(OrganizationInvitation).where(
        OrganizationInvitation.organization_id==org.id)).token == hashlib.sha256(second['token'].encode()).hexdigest()
    with pytest.raises(HTTPException) as err:
        accept_invitation(raw1, recipient, db)
    assert err.value.status_code==404
    new_member = accept_invitation(second['token'], recipient, db)
    assert new_member['user_id']==recipient.id


def test_outbox_lease_survives_nested_commit(db):
    row = EventOutbox(dedupe_key='test:' + uuid.uuid4().hex, topic='waste.report.progress',
                      payload={'record_id':str(uuid.uuid4()),'user_id':str(uuid.uuid4())})
    db.add(row)
    db.commit()
    def inner_commit(session, event):
        session.commit()
        assert db.get(EventOutbox, row.id).lease_owner is not None
        return 'completed'
    with patch.object(workflow_orchestrator, 'process_one', side_effect=inner_commit):
        result = workflow_orchestrator.run_workflow_batch(db)
    db.refresh(row)
    assert result['completed']==1
    assert row.delivered_at is not None and row.lease_owner is None


def test_outbox_retry_clears_lease(db):
    row=EventOutbox(dedupe_key='fail:' + uuid.uuid4().hex, topic='waste.report.progress',
                    payload={'record_id':str(uuid.uuid4()),'user_id':str(uuid.uuid4())})
    db.add(row)
    db.commit()
    with patch.object(workflow_orchestrator, 'process_one', side_effect=RuntimeError('failed')):
        result=workflow_orchestrator.run_workflow_batch(db)
    db.refresh(row)
    assert result['retry']==1 and row.attempts==1 and row.lease_owner is None


def test_closed_empty_invoice_cycle(db):
    owner = make_user(db, UserRole.HOSPITAL, 'invoice-owner')
    org = make_org(db, owner, 'HOSPITAL')
    hp = HospitalProfile(user_id=owner.id, organization_id=org.id, name='Demo hospital',
        registration_number='R100',contact_person='Owner',phone='123',address_line='Road',
        city='Khulna',region='Khulna',postal_code='9000')
    db.add(hp)
    contract=BillingContract(hospital_org_id=org.id,billing_anchor_local=date(2026,8,1),
                             cycle_days=15,due_days=15, active=True)
    db.add(contract)
    db.commit()
    inv=issue_invoice(db,contract,0)
    assert inv.gross_bdt==0 and inv.credits_bdt==0 and inv.due_bdt==0
    assert issue_invoice(db,contract,0).id == inv.id


def test_deployed_demo_still_requires_hardened_security():
    with pytest.raises(ValueError):
        Settings(environment='demo',debug=True,payment_mode='mock')
    with pytest.raises(ValueError):
        Settings(environment='demo', debug=False, payment_mode='mock',
            jwt_secret_key='strong-demo-jwt-key-unique-for-this-test-only',
            auth_cookie_secure=True)



def test_simulator_arrival_is_preview_not_verified_delivery():
    """A simulated vehicle reaching the last point cannot certify a real handover."""
    import asyncio
    from unittest.mock import AsyncMock
    from app.services.gps_simulator_service import GPSSimulatorService, SimulationState
    from app.realtime.tracking_manager import tracking_manager
    state = SimulationState(simulation_id=uuid.uuid4(),vehicle_id=uuid.uuid4(),
        route_id=uuid.uuid4(),tracking_session_id=uuid.uuid4(),
        speed_multiplier=1.0,status='RUNNING',progress=0.0)
    with patch.object(tracking_manager, 'broadcast', new_callable=AsyncMock) as broadcast:
        asyncio.run(GPSSimulatorService(Settings())._arrive_destination(state))
    assert state.status == 'AT_DESTINATION'
    event = broadcast.await_args.args[0]
    assert event['verified_arrival'] is False
    assert event['event'] == 'simulation.destination.preview'


def test_company_manager_can_view_fleet_but_unrelated_collector_cannot(db):
    driver = make_user(db, UserRole.COLLECTOR, 'company-fleet-driver')
    manager = make_user(db, UserRole.COLLECTOR, 'company-fleet-manager')
    outsider = make_user(db, UserRole.COLLECTOR, 'company-fleet-outsider')
    org = make_org(db, driver, 'COLLECTION_COMPANY')
    db.add(OrganizationMember(organization_id=org.id, user_id=manager.id,
                              member_role='manager', active=True))
    db.commit()
    van = VehicleService(db).create_vehicle(collector_id=driver.id,
        data=VehicleCreate(vehicle_code='FLEET-TEST', capacity_kg=Decimal('100'), organization_id=org.id))
    assert van.id in [v.id for v in VehicleService(db).list_my_vehicles(manager.id)]
    assert van.id not in [v.id for v in VehicleService(db).list_my_vehicles(outsider.id)]
    member = db.scalar(select(OrganizationMember).where(OrganizationMember.user_id == manager.id))
    member.active = False
    db.flush()
    assert van.id not in [v.id for v in VehicleService(db).list_my_vehicles(manager.id)]


def test_revoked_hospital_company_owner_cannot_read_linked_profile(db):
    from app.repositories.hospital_repository import HospitalRepository
    owner = make_user(db, UserRole.HOSPITAL, 'revoked-hospital-owner')
    org = make_org(db, owner, 'HOSPITAL')
    profile = HospitalProfile(user_id=owner.id, organization_id=org.id,
        name='Hospital A', registration_number='H-0001', contact_person='Officer',
        phone='01700000000', address_line='Khulna', city='Khulna',
        region='Khulna', postal_code='9000', is_verified=True)
    db.add(profile); db.commit()
    assert HospitalRepository(db).get_by_user_id(owner.id) is not None
    member = db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id == org.id))
    member.active = False; db.flush()
    assert HospitalRepository(db).get_by_user_id(owner.id) is None
    assert not can_manage_profile(db, profile, owner.id, 'HOSPITAL')


def test_revoked_facility_company_owner_cannot_read_linked_profile(db):
    from app.repositories.facility_repository import FacilityRepository
    owner = make_user(db, UserRole.FACILITY, 'revoked-facility-owner')
    org = make_org(db, owner, 'TREATMENT_FACILITY')
    profile = make_facility(db, owner, org)
    assert FacilityRepository(db).get_by_user_id(owner.id) is not None
    member = db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id == org.id))
    member.active = False; db.flush()
    assert FacilityRepository(db).get_by_user_id(owner.id) is None
    assert not can_manage_profile(db, profile, owner.id, 'TREATMENT_FACILITY')
