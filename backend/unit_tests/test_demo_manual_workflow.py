"""Manual test flow must never impersonate GPS evidence and is off by default.

Run: DATABASE_URL=sqlite+pysqlite:///:memory: python -m pytest -q unit_tests/test_demo_manual_workflow.py
"""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.core.config import Settings, get_settings
from app.core.db import Base
from app.models.audit_log import AuditLog
from app.models.pickup_request import PickupRequest, PickupRequestItem
from app.models.roles import UserRole
from app.models.route import Route, RouteStatus, RouteStop, RouteStopStatus
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.waste_enums import PickupPriority, PickupStatus, VehicleStatus, WasteStatus, WasteUnit
from app.models.waste_record import WasteRecord
from app.services.pickup_service import PickupNotCollectableError, PickupService, NotAssignedCollectorError


@pytest.fixture
def scenario(monkeypatch):
    monkeypatch.setenv('ENVIRONMENT', 'test')
    monkeypatch.setenv('ENABLE_DEMO_MANUAL_WORKFLOW', 'true')
    get_settings.cache_clear()
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        driver = User(email='driver-demo@example.test', full_name='Driver', hashed_password='x', role=UserRole.COLLECTOR, is_active=True)
        other = User(email='other-demo@example.test', full_name='Other', hashed_password='x', role=UserRole.COLLECTOR, is_active=True)
        db.add_all([driver, other]); db.flush()
        van = Vehicle(vehicle_code='DEMO-001', assigned_collector_id=driver.id, status=VehicleStatus.ON_ROUTE, is_active=True, capacity_kg=Decimal('300'))
        db.add(van); db.flush()
        pickup = PickupRequest(hospital_id=uuid4(), status=PickupStatus.ASSIGNED, priority=PickupPriority.NORMAL,
                               assigned_collector_id=driver.id, assigned_vehicle_id=van.id)
        waste = WasteRecord(waste_code=f'MW-DEMO-{uuid4().hex[:8]}', hospital_id=pickup.hospital_id,
                            category_id=uuid4(), quantity=Decimal('10'), unit=WasteUnit.KG,
                            status=WasteStatus.PICKUP_ASSIGNED, generated_at=datetime.now(timezone.utc))
        pickup.items.append(PickupRequestItem(waste_record=waste))
        db.add(pickup); db.flush()
        route = Route(vehicle_id=van.id, status=RouteStatus.ACTIVE)
        db.add(route); db.flush()
        stop = RouteStop(route_id=route.id, pickup_id=pickup.id, sequence=1,
                         latitude=Decimal('22.83'), longitude=Decimal('89.54'), status=RouteStopStatus.EN_ROUTE)
        db.add(stop); db.commit()
        yield db, pickup, stop, driver, other, waste
    engine.dispose()
    get_settings.cache_clear()


def test_demo_manual_arrival_requires_correct_qr_and_driver(scenario):
    db, pickup, stop, driver, other, waste = scenario
    svc = PickupService(db)
    with pytest.raises(PickupNotCollectableError):
        svc.mark_arrived(collector_id=driver.id, pickup_id=pickup.id, token='wrong', demo_manual=True)
    with pytest.raises(NotAssignedCollectorError):
        svc.mark_arrived(collector_id=other.id, pickup_id=pickup.id, token=pickup.handover_token, demo_manual=True)
    assert stop.status == RouteStopStatus.EN_ROUTE
    arrived = svc.mark_arrived(collector_id=driver.id, pickup_id=pickup.id,
                              token=pickup.handover_token, demo_manual=True)
    assert arrived.status == RouteStopStatus.ARRIVED
    assert db.scalar(select(AuditLog).where(AuditLog.action == 'pickup.arrival.demo_manual')).details['simulated'] is True
    assert any(e.event_metadata.get('simulated') for e in svc.events.list_timeline(waste.id))
    with pytest.raises(PickupNotCollectableError):
        svc.mark_arrived(collector_id=driver.id, pickup_id=pickup.id,
                         token=pickup.handover_token, demo_manual=True)


def test_demo_arrival_disabled_even_for_assigned_driver(scenario, monkeypatch):
    db, pickup, stop, driver, other, waste = scenario
    monkeypatch.setenv('ENABLE_DEMO_MANUAL_WORKFLOW', 'false')
    get_settings.cache_clear()
    with pytest.raises(PickupNotCollectableError):
        PickupService(db).mark_arrived(collector_id=driver.id, pickup_id=pickup.id,
                                       token=pickup.handover_token, demo_manual=True)
    assert stop.status == RouteStopStatus.EN_ROUTE


def test_cannot_enable_demo_manual_in_production():
    with pytest.raises(ValueError, match='ENABLE_DEMO_MANUAL_WORKFLOW'):
        Settings(environment='production', enable_demo_manual_workflow=True, debug=False,
                 jwt_secret_key='this_is_a_very_long_unique_test_secret_key_only',
                 auth_cookie_secure=True, frontend_public_base_url='https://example.test')