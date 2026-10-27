"""Issue 10: prevents auto-dispatch to disabled/wrong-org/unauthorized drivers."""
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.core.db import Base
from app.models.business import Organization, OrganizationMember
from app.models.roles import UserRole
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.waste_enums import VehicleStatus, PickupStatus, PickupPriority
from app.services.pickup_service import PickupService


@pytest.fixture
def fleet():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        driver = User(email='driver10@example.test', full_name='Driver', role=UserRole.COLLECTOR,
                      hashed_password='x', is_active=True)
        db.add(driver); db.flush()
        org = Organization(name='Collector Company', org_type='COLLECTION_COMPANY', status='verified', owner_user_id=driver.id)
        another = Organization(name='Other Company', org_type='COLLECTION_COMPANY', status='verified', owner_user_id=driver.id)
        db.add_all([org, another]); db.flush()
        membership = OrganizationMember(organization_id=org.id, user_id=driver.id, member_role='driver', active=True)
        vehicle = Vehicle(vehicle_code='ISSUE10-C', assigned_collector_id=driver.id,
                          organization_id=org.id, status=VehicleStatus.AVAILABLE, is_active=True, capacity_kg=Decimal('500'))
        db.add_all([membership, vehicle]); db.commit()
        yield db, driver, org, another, membership, vehicle
    engine.dispose()


def eligible(fleet):
    db, driver, org, another, membership, vehicle = fleet
    return PickupService(db)._vehicle_has_eligible_driver(vehicle)


def test_eligible_company_driver_is_accepted(fleet):
    assert eligible(fleet)

@pytest.mark.parametrize('role', [UserRole.ADMIN, UserRole.HOSPITAL, UserRole.FACILITY])
def test_noncollector_accounts_are_rejected(fleet, role):
    db, driver, *rest = fleet
    driver.role = role; db.commit()
    assert not eligible(fleet)


def test_disabled_user_is_rejected(fleet):
    db, driver, *rest = fleet
    driver.is_active = False; db.commit()
    assert not eligible(fleet)


def test_revoked_company_membership_is_rejected(fleet):
    db, driver, org, another, member, vehicle = fleet
    member.active = False; db.commit()
    assert not eligible(fleet)


def test_wrong_company_membership_is_rejected(fleet):
    db, driver, org, another, member, vehicle = fleet
    member.organization_id = another.id; db.commit()
    assert not eligible(fleet)

@pytest.mark.parametrize('member_role', ['worker', 'finance'])
def test_ineligible_membership_role_is_rejected(fleet, member_role):
    db, driver, org, another, member, vehicle = fleet
    member.member_role = member_role; db.commit()
    assert not eligible(fleet)

@pytest.mark.parametrize('member_role', ['owner', 'manager', 'dispatcher', 'driver'])
def test_legacy_authorized_membership_roles_stay_eligible(fleet, member_role):
    db, driver, org, another, member, vehicle = fleet
    member.member_role = member_role; db.commit()
    assert eligible(fleet)


def test_unscoped_legacy_demo_vehicle_still_checks_account(fleet):
    db, driver, org, another, member, vehicle = fleet
    vehicle.organization_id = None; db.commit()
    assert eligible(fleet)
    driver.is_active = False; db.commit()
    assert not eligible(fleet)


def test_auto_assign_skips_ineligible_driver_and_preserves_requested_status(fleet, monkeypatch):
    """Use actual assignment method and SQL candidate enumeration; stub only external stages."""
    import app.services.pickup_service as ps
    db, driver, org, another, member, vehicle = fleet
    member.active = False
    db.commit()
    service = PickupService(db)
    facility_id = uuid.uuid4()
    dummy_record = SimpleNamespace(id=uuid.uuid4(), quantity=Decimal('5'), unit='kg')
    dummy_item = SimpleNamespace(waste_record_id=dummy_record.id, waste_record=dummy_record)
    pickup = SimpleNamespace(items=[dummy_item], priority=PickupPriority.NORMAL,
        status=PickupStatus.REQUESTED, requested_pickup_at=None, requested_pickup_end_at=None,
        assigned_vehicle_id=None, assigned_collector_id=None, scheduled_at=None)
    service.matches = SimpleNamespace(get_confirmed_for_record=lambda record_id: SimpleNamespace(confirmed_facility_id=facility_id))
    service.pickups = SimpleNamespace(save=lambda obj, commit=False: None)
    def fake_schedule(**kwargs):
        assert kwargs['candidate_vehicles'] == []
        return SimpleNamespace(vehicle=None, scheduled_at=None)
    with patch.object(ps, 'operator_accepts_new_work', return_value=True), \
        patch.object(ps, 'schedule_pickup', side_effect=fake_schedule), \
        patch.object(service.records, 'set_status'):
        service._run_auto_assignment(pickup, required_capacity=Decimal('5'))
    assert pickup.status == PickupStatus.REQUESTED
    assert pickup.assigned_vehicle_id is None
    assert db.get(Vehicle, vehicle.id).status == VehicleStatus.AVAILABLE


def test_auto_assign_accepts_valid_driver(fleet, monkeypatch):
    import app.services.pickup_service as ps
    db, driver, org, another, member, vehicle = fleet
    service = PickupService(db)
    facility_id = uuid.uuid4()
    dummy_record = SimpleNamespace(id=uuid.uuid4(), quantity=Decimal('5'), unit='kg', status=None)
    dummy_item = SimpleNamespace(waste_record_id=dummy_record.id, waste_record=dummy_record)
    pickup = SimpleNamespace(items=[dummy_item], priority=PickupPriority.NORMAL,
        status=PickupStatus.REQUESTED, requested_pickup_at=None, requested_pickup_end_at=None,
        assigned_vehicle_id=None, assigned_collector_id=None, scheduled_at=None)
    service.matches = SimpleNamespace(get_confirmed_for_record=lambda record_id: SimpleNamespace(confirmed_facility_id=facility_id))
    service.pickups = SimpleNamespace(save=lambda obj, commit=False: None)
    service.events = SimpleNamespace(record=lambda **kwargs: None)
    def fake_schedule(**kwargs):
        assert kwargs['candidate_vehicles'] == [vehicle]
        return SimpleNamespace(vehicle=vehicle, scheduled_at=None)
    with patch.object(ps, 'operator_accepts_new_work', return_value=True), \
        patch.object(ps, 'schedule_pickup', side_effect=fake_schedule), \
        patch.object(service.records, 'set_status'):
        service._run_auto_assignment(pickup, required_capacity=Decimal('5'))
    assert pickup.status == PickupStatus.ASSIGNED
    assert pickup.assigned_collector_id == driver.id
    assert vehicle.status == VehicleStatus.RESERVED
