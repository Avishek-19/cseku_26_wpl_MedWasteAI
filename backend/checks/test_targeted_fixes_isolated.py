"""Issue 1/4/5/6/9 regression checks (SQLite only; not PostgreSQL E2E)."""
from __future__ import annotations

import base64
import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.core.config import Settings
from app.core.db import Base
from app.models.business import Organization, OrganizationMember, OrganizationPermit
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.roles import UserRole
from app.models.route import Route, RouteStatus, RouteStop, RouteStopStatus
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.pickup_request import PickupRequest
from app.models.waste_enums import PickupPriority, PickupStatus, VehicleStatus
from app.schemas.vehicle import VehicleCreate, VehicleUpdate
from app.services.route_optimization_service import RouteOptimizationService, RouteValidationError, Point
from app.services.tracking_service import TrackingService
from app.services.vehicle_service import VehicleService, VehicleConflictError
from app.services.pickup_service import PickupService


@pytest.fixture
def db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def make_user(db, role, name):
    user = User(full_name=name, email=f'{name}-{uuid.uuid4().hex[:7]}@example.test',
                hashed_password='unused', role=role, is_active=True)
    db.add(user); db.flush()
    return user


def make_company(db, owner, kind='COLLECTION_COMPANY'):
    org = Organization(name='Test Organization', owner_user_id=owner.id,
                       org_type=kind, status='verified')
    db.add(org); db.flush()
    db.add(OrganizationMember(user_id=owner.id, organization_id=org.id,
                              member_role='owner', active=True))
    db.flush()
    return org


def make_planned_route(db):
    driver = make_user(db, UserRole.COLLECTOR, 'driver')
    hospital_owner = make_user(db, UserRole.HOSPITAL, 'hospital')
    from app.models.hospital_profile import HospitalProfile
    hospital = HospitalProfile(user_id=hospital_owner.id, name='Hospital', registration_number='r',
        contact_person='A', phone='123', address_line='Street', city='Khulna', region='Khulna', postal_code='9000')
    db.add(hospital); db.flush()
    vehicle = Vehicle(vehicle_code=f'CAR-{uuid.uuid4().hex[:5]}', assigned_collector_id=driver.id,
                      capacity_kg=Decimal('100'), status=VehicleStatus.RESERVED)
    db.add(vehicle); db.flush()
    pickup = PickupRequest(hospital_id=hospital.id,requested_by=hospital_owner.id,
        priority=PickupPriority.NORMAL, status=PickupStatus.ASSIGNED,
        assigned_collector_id=driver.id, assigned_vehicle_id=vehicle.id)
    db.add(pickup); db.flush()
    route = Route(vehicle_id=vehicle.id,version=1,status=RouteStatus.DRAFT,
                  origin_latitude=Decimal('22.8'),origin_longitude=Decimal('89.5'),
                  destination_latitude=Decimal('22.9'),destination_longitude=Decimal('89.6'))
    db.add(route);db.flush()
    db.add(RouteStop(route_id=route.id,pickup_id=pickup.id,sequence=1,
                     latitude=Decimal('22.8'),longitude=Decimal('89.5'),status=RouteStopStatus.PENDING))
    db.commit()
    return driver, vehicle, pickup, route


def route_service(db):
    return RouteOptimizationService(db, Settings(database_url='sqlite+pysqlite:///:memory:', routing_provider='haversine'))


def test_route_draft_must_confirm_before_start(db):
    driver, vehicle, pickup, route = make_planned_route(db)
    service=route_service(db)
    with pytest.raises(RouteValidationError, match='Confirm the route'):
        service.start(user=driver,route_id=route.id)
    assert db.get(Route,route.id).status == RouteStatus.DRAFT
    # This fixture has no facility matching records; only the confirmation
    # state machine is under test. Facility validation has dedicated checks.
    with patch.object(service, '_destination', return_value=Point(22.9,89.6)), patch.object(
        service, '_validate_dispatch_destination', return_value=None
    ):
        confirmed=service.confirm(user=driver,route_id=route.id)
        assert confirmed.status == RouteStatus.READY
        assert service.confirm(user=driver,route_id=route.id).status == RouteStatus.READY  # idempotent


def test_start_stops_when_facility_is_suspended(db):
    driver, vehicle, pickup, route = make_planned_route(db)
    service=route_service(db)
    route.status = RouteStatus.READY
    db.commit()
    with patch.object(service, '_destination', return_value=Point(22.9,89.6)), patch.object(
        service, '_validate_dispatch_destination', side_effect=RouteValidationError('facility no longer eligible')):
        with pytest.raises(RouteValidationError, match='facility no longer eligible'):
            service.start(user=driver,route_id=route.id)
    assert db.get(Route,route.id).status == RouteStatus.READY
    assert db.get(Vehicle,vehicle.id).status == VehicleStatus.RESERVED


def test_facility_permit_availability_capability_and_capacity_are_rechecked(db):
    fac_owner = make_user(db, UserRole.FACILITY, 'facility')
    org = make_company(db,fac_owner,kind='TREATMENT_FACILITY')
    permit = OrganizationPermit(organization_id=org.id,permit_type='Waste treatment',
        reference='P',expires_on=date.today()+timedelta(days=4),approval_status='approved')
    db.add(permit)
    facility = TreatmentFacilityProfile(user_id=fac_owner.id,organization_id=org.id,
        name='Facility', registration_number='F',contact_person='A',phone='12',
        address_line='X',city='Khulna',region='Khulna',postal_code='9000',
        latitude=Decimal('22.9'),longitude=Decimal('89.6'),is_verified=True,
        capacity_kg=Decimal('200'),current_utilization_kg=Decimal('100'),
        availability_status='available',processing_services=['INCINERATION'])
    db.add(facility);db.commit()
    from app.models.facility_accepted_category import FacilityAcceptedCategory
    from app.models.waste_category import WasteCategory
    category=WasteCategory(code='INFECTIOUS',name='Infectious test waste',is_recyclable=False)
    db.add(category);db.flush()
    acceptance=FacilityAcceptedCategory(facility_id=facility.id,category_id=category.id)
    db.add(acceptance);db.flush()
    record_id=uuid.uuid4()
    fake_match=SimpleNamespace(is_confirmed=True,confirmed_facility_id=facility.id,
        candidates=[{'id':str(facility.id),'processing_method':'INCINERATION'}],processing_method='INCINERATION')
    fake_pickup=SimpleNamespace(items=[SimpleNamespace(waste_record_id=record_id,
        waste_record=SimpleNamespace(category_id=category.id))])
    service=route_service(db)
    with patch.object(service.matches,'get_confirmed_for_record',return_value=fake_match):
        service._validate_dispatch_destination([fake_pickup])
        facility.processing_services=['RECYCLING']; db.flush()
        with pytest.raises(RouteValidationError,match='no longer authorized'):
            service._validate_dispatch_destination([fake_pickup])
        facility.processing_services=['INCINERATION']; facility.availability_status='unavailable';db.flush()
        with pytest.raises(RouteValidationError):service._validate_dispatch_destination([fake_pickup])
        facility.availability_status='available';permit.expires_on=date.today()-timedelta(days=1);db.flush()
        with pytest.raises(RouteValidationError):service._validate_dispatch_destination([fake_pickup])
        permit.expires_on=date.today()+timedelta(days=4);facility.current_utilization_kg=Decimal('201');db.flush()
        with pytest.raises(RouteValidationError,match='capacity'):
            service._validate_dispatch_destination([fake_pickup])
        facility.current_utilization_kg=Decimal('100');db.delete(acceptance);db.flush()
        with pytest.raises(RouteValidationError,match='no longer accepts'):
            service._validate_dispatch_destination([fake_pickup])


def test_driver_assignment_is_explicit_and_other_driver_cannot_write_gps(db):
    owner=make_user(db,UserRole.COLLECTOR,'owner')
    driver=make_user(db,UserRole.COLLECTOR,'driver')
    unrelated=make_user(db,UserRole.COLLECTOR,'unrelated')
    org=make_company(db,owner)
    db.add(OrganizationMember(organization_id=org.id,user_id=driver.id,
                              member_role='driver',active=True));db.flush()
    svc=VehicleService(db)
    with pytest.raises(VehicleConflictError,match='active owner'):
        svc.create_vehicle(collector_id=owner.id,data=VehicleCreate(vehicle_code='X',
            capacity_kg=Decimal('40'),organization_id=org.id,assigned_collector_id=unrelated.id))
    vehicle=svc.create_vehicle(collector_id=owner.id,data=VehicleCreate(vehicle_code='V1',
        capacity_kg=Decimal('40'),organization_id=org.id,assigned_collector_id=driver.id))
    assert vehicle.assigned_collector_id == driver.id
    track=TrackingService(db,Settings(database_url='sqlite+pysqlite:///:memory:'))
    assert track._can_manage_vehicle(driver,vehicle)
    assert not track._can_manage_vehicle(owner,vehicle)  # owner cannot spoof driver GPS
    assert not track._can_manage_vehicle(unrelated,vehicle)
    route=route_service(db)
    assert route._can_manage(owner,vehicle)  # dispatcher can plan the company's own route
    assert route._can_manage(driver,vehicle)
    assert not route._can_manage(unrelated,vehicle)
    vehicle.status=VehicleStatus.RESERVED;db.flush()
    with pytest.raises(VehicleConflictError,match='AVAILABLE'):
        svc.update_vehicle(collector_id=owner.id,vehicle_id=vehicle.id,
                           data=VehicleUpdate(assigned_collector_id=owner.id))
    vehicle.status=VehicleStatus.AVAILABLE;db.flush()
    updated=svc.update_vehicle(collector_id=owner.id,vehicle_id=vehicle.id,
                               data=VehicleUpdate(assigned_collector_id=owner.id))
    assert updated.assigned_collector_id == owner.id


def test_qr_api_returns_scannable_svg_only_for_assigned_pickup(db):
    driver,vehicle,pickup,route=make_planned_route(db)
    hospital=db.get(User,pickup.requested_by)
    # real hospital ownership authorization is exercised by PickupService; it is
    # intentionally not mocked for this check.
    pytest.importorskip("bcrypt")
    from app.api.pickups import hospital_handover_qr
    from fastapi import Response
    http_response=Response()
    qr= hospital_handover_qr(pickup_id=pickup.id,response=http_response,current_user=hospital,db=db)
    assert http_response.headers["Cache-Control"] == "private, no-store"
    assert qr['handover_qr'] == pickup.handover_token
    assert qr['qr_svg_data_url'].startswith('data:image/svg+xml;base64,')
    svg=base64.b64decode(qr['qr_svg_data_url'].split(',')[1])
    assert b'<svg' in svg and b'<path' in svg
    pickup.status=PickupStatus.COLLECTED;db.flush()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        hospital_handover_qr(pickup_id=pickup.id,response=Response(),current_user=hospital,db=db)
    assert caught.value.status_code==409


def test_handover_action_requires_proof_not_empty_payload():
    pytest.importorskip("bcrypt")
    from app.api.pickups import HandoverRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError): HandoverRequest.model_validate({})
    result=HandoverRequest.model_validate({
        'handover_qr':'x'*30,'actual_weight_kg':'12.500','packaging_condition':'sealed'})
    assert result.actual_weight_kg == Decimal('12.500')
