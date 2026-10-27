"""Issue 9: exercise the real admin discovery and audited approval endpoints.

SQLite isolated; POST is also protected by FastAPI require_roles dependency.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.core.db import Base
from app.api.admin import pickup_arrival_exception_candidates
from app.api.pickups import ArrivalExceptionApproval, approve_no_gps_arrival
from app.models.audit_log import AuditLog
from app.models.hospital_profile import HospitalProfile
from app.models.pickup_request import PickupRequest
from app.models.roles import UserRole
from app.models.route import Route, RouteStatus, RouteStop, RouteStopStatus
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.waste_enums import PickupPriority, PickupStatus, VehicleStatus


@pytest.fixture
def cases():
    engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        driver = User(email='drive9@example.test', hashed_password='x', full_name='Driver', role=UserRole.COLLECTOR, is_active=True)
        admin = User(email='admin9@example.test', hashed_password='x', full_name='Admin', role=UserRole.ADMIN, is_active=True)
        hosp = User(email='hospital9@example.test', hashed_password='x', full_name='Hospital', role=UserRole.HOSPITAL, is_active=True)
        db.add_all([driver, admin, hosp]); db.flush()
        profile = HospitalProfile(user_id=hosp.id, name='K Hospital', registration_number='kh09',
            contact_person='Office', phone='000', address_line='A Street', city='Khulna', region='Khulna', postal_code='9000')
        van = Vehicle(vehicle_code='TEST-009', assigned_collector_id=driver.id, capacity_kg=Decimal('500'), status=VehicleStatus.ON_ROUTE, is_active=True)
        db.add_all([profile, van]); db.flush()
        pickup = PickupRequest(hospital_id=profile.id, priority=PickupPriority.NORMAL,
            status=PickupStatus.ASSIGNED, assigned_vehicle_id=van.id, assigned_collector_id=driver.id)
        db.add(pickup); db.flush()
        route = Route(vehicle_id=van.id, status=RouteStatus.ACTIVE)
        db.add(route); db.flush()
        stop = RouteStop(route_id=route.id, pickup_id=pickup.id, sequence=1,
            latitude=Decimal('22.80'), longitude=Decimal('89.50'), status=RouteStopStatus.EN_ROUTE)
        db.add(stop); db.commit()
        yield db, pickup, route, stop, van, driver, admin
    engine.dispose()


def test_admin_candidate_list_contains_only_active_enroute(cases):
    db, pickup, route, stop, van, driver, admin = cases
    items = pickup_arrival_exception_candidates(current_user=admin, db=db)
    assert len(items) == 1
    assert items[0]['pickup_id'] == str(pickup.id)
    assert items[0]['hospital_name'] == 'K Hospital'
    assert items[0]['vehicle_code'] == 'TEST-009'
    assert not any('handover' in key or 'token' in key for key in items[0])
    stop.status = RouteStopStatus.ARRIVED; db.commit()
    assert pickup_arrival_exception_candidates(current_user=admin, db=db) == []
    stop.status = RouteStopStatus.EN_ROUTE; route.status = RouteStatus.COMPLETED; db.commit()
    assert pickup_arrival_exception_candidates(current_user=admin, db=db) == []


def test_admin_candidate_list_rejects_mismatched_vehicle_driver(cases):
    db, pickup, route, stop, van, driver, admin = cases
    pickup.assigned_collector_id = uuid.uuid4(); db.commit()
    assert pickup_arrival_exception_candidates(current_user=admin, db=db) == []


def test_admin_approval_audited_and_time_limited_without_setting_arrival(cases):
    db, pickup, route, stop, van, driver, admin = cases
    response = approve_no_gps_arrival(pickup_id=pickup.id,
        payload=ArrivalExceptionApproval(reason='Independently checked vehicle at hospital gate'),
        current_user=admin, db=db)
    assert response['approved'] is True
    assert response['valid_for_seconds'] == 1200
    assert response['requires_hospital_qr'] is True
    db.refresh(stop)
    assert stop.status == RouteStopStatus.EN_ROUTE  # separate driver QR action required
    logs = db.scalars(select(AuditLog).where(AuditLog.entity_id == str(pickup.id))).all()
    assert len(logs) == 1
    assert logs[0].actor_user_id == admin.id
    assert logs[0].details['route_stop_id'] == str(stop.id)
    assert logs[0].details['reason'] == 'Independently checked vehicle at hospital gate'


def test_approval_rejected_without_enroute_stop(cases):
    db, pickup, route, stop, van, driver, admin = cases
    stop.status = RouteStopStatus.CANCELLED; db.commit()
    with pytest.raises(HTTPException) as err:
        approve_no_gps_arrival(pickup_id=pickup.id,
            payload=ArrivalExceptionApproval(reason='Physical handover was independently verified'),
            current_user=admin, db=db)
    assert err.value.status_code == 409


def test_approval_short_reason_rejected_by_schema():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ArrivalExceptionApproval(reason='Short')


def test_candidate_endpoint_requires_admin_role(cases):
    """Execute the actual FastAPI dependency chain with a non-admin user."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.admin import router as admin_router
    from app.api.deps import get_current_user
    from app.core.db import get_db
    db, pickup, route, stop, van, driver, admin = cases
    app = FastAPI()
    app.include_router(admin_router, prefix='/api/v1')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: driver
    with TestClient(app) as client:
        denied = client.get('/api/v1/admin/pickup-arrival-exception-candidates')
        assert denied.status_code == 403
        app.dependency_overrides[get_current_user] = lambda: admin
        allowed = client.get('/api/v1/admin/pickup-arrival-exception-candidates')
        assert allowed.status_code == 200
        assert len(allowed.json()) == 1
    app.dependency_overrides.clear()


def test_actual_driver_no_gps_arrival_requires_matching_supervisor_reason_and_qr(cases):
    """Approval must still be followed by driver hospital QR verification."""
    from app.services.pickup_service import PickupService, PickupNotCollectableError
    db, pickup, route, stop, van, driver, admin = cases
    approved_reason = 'Gate supervisor confirmed physical driver arrival'
    with pytest.raises(PickupNotCollectableError):
        PickupService(db).mark_arrived(
            collector_id=driver.id, pickup_id=pickup.id,
            token=pickup.handover_token, manual_reason=approved_reason)
    db.rollback()
    approve_no_gps_arrival(pickup_id=pickup.id,
        payload=ArrivalExceptionApproval(reason=approved_reason),
        current_user=admin, db=db)
    with pytest.raises(PickupNotCollectableError):
        PickupService(db).mark_arrived(
            collector_id=driver.id, pickup_id=pickup.id,
            token=pickup.handover_token, manual_reason='Different independent no-GPS reason')
    db.rollback()
    with pytest.raises(PickupNotCollectableError):
        PickupService(db).mark_arrived(
            collector_id=driver.id, pickup_id=pickup.id,
            token='incorrectQrValue', manual_reason=approved_reason)
    db.rollback()
    result = PickupService(db).mark_arrived(
        collector_id=driver.id, pickup_id=pickup.id,
        token=pickup.handover_token, manual_reason=approved_reason)
    assert result.status == RouteStopStatus.ARRIVED
    assert db.scalar(select(AuditLog.id).where(
        AuditLog.action == 'pickup.arrival.gps_exception_used',
        AuditLog.entity_id == str(pickup.id))) is not None
