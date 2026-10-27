"""Issue 1 regression tests: complete pickups only after all batches reach the facility.

Uses an isolated SQLite ORM database so it is safe to run without touching the
real PostgreSQL deployment. Run from backend with:
  DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q unit_tests/test_issue1_pickup_delivery_completion.py
(PostgreSQL integration tests must still be run in the actual application environment.)
"""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # noqa: F401 register mapped tables
from app.core.db import Base
from app.models.pickup_request import PickupRequest, PickupRequestItem
from app.models.route import Route, RouteStatus, RouteStop, RouteDestinationState
from app.models.tracking import TrackingSession, TrackingSessionStatus
from app.models.vehicle import Vehicle
from app.models.waste_enums import PickupPriority, PickupStatus, VehicleStatus, WasteStatus, WasteUnit
from app.models.waste_record import WasteRecord
from app.services.receiving_service import ReceivingService


@pytest.fixture
def db():
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as session:
        yield session
    engine.dispose()


def setup_route(db, *, weights=(1,), with_tracking=False, extra_assigned=False, initial_pickup_status=PickupStatus.IN_TRANSIT):
    """Create a route with n distinct pickups, each containing one batch."""
    now = datetime.now(timezone.utc)
    vehicle = Vehicle(id=uuid4(), vehicle_code=f'VAN-{uuid4().hex[:10]}',
                      assigned_collector_id=uuid4(), capacity_kg=Decimal('500'), status=VehicleStatus.ON_ROUTE)
    db.add(vehicle)
    session = None
    if with_tracking:
        session = TrackingSession(id=uuid4(), vehicle_id=vehicle.id, status=TrackingSessionStatus.ACTIVE)
        db.add(session)
    route = Route(id=uuid4(), vehicle_id=vehicle.id, tracking_session_id=session.id if session else None,
                  status=RouteStatus.ACTIVE, destination_state=RouteDestinationState.AT_DESTINATION.value,
                  destination_arrived_at=now)
    db.add(route)
    pickups, records = [], []
    for idx, weight in enumerate(weights):
        pickup = PickupRequest(id=uuid4(), hospital_id=uuid4(), priority=PickupPriority.NORMAL,
                               status=initial_pickup_status, assigned_vehicle_id=vehicle.id,
                               assigned_collector_id=vehicle.assigned_collector_id)
        record = WasteRecord(id=uuid4(), waste_code=f'MW-ISSUE1-{uuid4().hex[:8]}',
                             hospital_id=pickup.hospital_id, category_id=uuid4(),
                             quantity=Decimal(str(weight)), unit=WasteUnit.KG,
                             status=WasteStatus.IN_TRANSIT, generated_at=now)
        pickup.items.append(PickupRequestItem(waste_record=record))
        db.add_all([pickup, record])
        db.add(RouteStop(route_id=route.id, pickup_id=pickup.id,
                         sequence=idx + 1, latitude=Decimal('22.8'), longitude=Decimal('89.5')))
        pickups.append(pickup)
        records.append(record)
    reserved = None
    if extra_assigned:
        reserved = PickupRequest(id=uuid4(), hospital_id=uuid4(), priority=PickupPriority.NORMAL,
                                 status=PickupStatus.ASSIGNED, assigned_vehicle_id=vehicle.id)
        db.add(reserved)
    db.commit()
    return route, vehicle, pickups, records, session, reserved


def receive(db, record):
    now = datetime.now(timezone.utc)
    record.status = WasteStatus.DESTINATION_RECEIVED
    db.flush()
    return ReceivingService(db)._complete_transport_if_ready(record.id, now)


def test_single_pickup_receipt_completes_pickup_route_vehicle_and_tracking(db):
    route, vehicle, pickups, records, tracking, _ = setup_route(db, with_tracking=True)
    completed_routes, completed_pickups = receive(db, records[0])
    assert [p.id for _, p in completed_pickups] == [pickups[0].id]
    assert [r.id for r, _ in completed_routes] == [route.id]
    assert pickups[0].status == PickupStatus.COMPLETED
    assert route.status == RouteStatus.COMPLETED
    assert route.destination_state == RouteDestinationState.COMPLETED.value
    assert vehicle.status == VehicleStatus.AVAILABLE
    assert tracking.status == TrackingSessionStatus.COMPLETED
    assert tracking.ended_at is not None
    db.commit()
    db.expire_all()
    assert db.get(PickupRequest, pickups[0].id).status == PickupStatus.COMPLETED


def test_multi_pickup_route_remains_active_until_last_received(db):
    route, vehicle, pickups, records, _, _ = setup_route(db, weights=(3, 4))
    routes1, pickups1 = receive(db, records[0])
    assert routes1 == []
    assert len(pickups1) == 1 and pickups1[0][1].id == pickups[0].id
    assert pickups[0].status == PickupStatus.COMPLETED
    assert pickups[1].status == PickupStatus.IN_TRANSIT
    assert route.status == RouteStatus.ACTIVE
    assert vehicle.status == VehicleStatus.ON_ROUTE
    routes2, pickups2 = receive(db, records[1])
    assert len(routes2) == 1 and len(pickups2) == 1
    assert pickups[1].status == PickupStatus.COMPLETED
    assert route.status == RouteStatus.COMPLETED
    assert vehicle.status == VehicleStatus.AVAILABLE


def test_multi_batch_pickup_not_completed_on_partial_receipt(db):
    route, vehicle, pickups, records, _, _ = setup_route(db)
    additional = WasteRecord(id=uuid4(), waste_code=f'MW-ISSUE1-{uuid4().hex[:8]}',
                             hospital_id=pickups[0].hospital_id, category_id=uuid4(),
                             quantity=Decimal('4'), unit=WasteUnit.KG, status=WasteStatus.IN_TRANSIT,
                             generated_at=datetime.now(timezone.utc))
    pickups[0].items.append(PickupRequestItem(waste_record=additional))
    db.add(additional)
    db.commit()
    routes1, pickups1 = receive(db, records[0])
    assert routes1 == [] and pickups1 == []
    assert pickups[0].status == PickupStatus.IN_TRANSIT
    assert route.status == RouteStatus.ACTIVE
    routes2, pickups2 = receive(db, additional)
    assert len(routes2) == 1 and len(pickups2) == 1
    assert pickups[0].status == PickupStatus.COMPLETED


def test_vehicle_stays_reserved_for_other_assigned_pickup(db):
    route, vehicle, pickups, records, _, reserved = setup_route(db, extra_assigned=True)
    routes, changed = receive(db, records[0])
    assert len(routes) == 1 and len(changed) == 1
    assert reserved.status == PickupStatus.ASSIGNED
    assert vehicle.status == VehicleStatus.RESERVED


def test_does_not_force_undelivered_or_cancelled_pickups_to_completed(db):
    route, vehicle, pickups, records, _, _ = setup_route(db, initial_pickup_status=PickupStatus.CANCELLED)
    routes, changed = receive(db, records[0])
    assert routes == [] and changed == []
    assert pickups[0].status == PickupStatus.CANCELLED
    assert route.status == RouteStatus.ACTIVE
    assert vehicle.status == VehicleStatus.ON_ROUTE


def test_delivery_transition_rolls_back_atomically(db):
    route, vehicle, pickups, records, _, _ = setup_route(db)
    pickup_id, record_id, route_id = pickups[0].id, records[0].id, route.id
    receive(db, records[0])
    db.flush()
    db.rollback()
    db.expire_all()
    assert db.get(PickupRequest, pickup_id).status == PickupStatus.IN_TRANSIT
    assert db.get(WasteRecord, record_id).status == WasteStatus.IN_TRANSIT
    assert db.get(Route, route_id).status == RouteStatus.ACTIVE


def test_successive_receipts_dont_re_complete_finished_pickup(db):
    route, vehicle, pickups, records, _, _ = setup_route(db, weights=(3, 5))
    routes1, pickups1 = receive(db, records[0]); db.commit()
    routes2, pickups2 = receive(db, records[1]); db.commit()
    assert routes1 == [] and len(pickups1) == 1
    assert len(routes2) == 1
    assert [p.id for _, p in pickups2] == [pickups[1].id]


def test_full_receipt_service_commits_pickup_and_broadcasts_after_commit(db, monkeypatch):
    """Exercise confirm_receipt(), not only its route-completion helper."""
    from app.realtime.tracking_manager import tracking_manager
    import app.services.organization_eligibility as eligibility

    route, vehicle, pickups, records, _, _ = setup_route(db)
    facility = SimpleNamespace(id=uuid4(), name='Demo Treatment Facility')
    actor_id = uuid4()
    service = ReceivingService(db)
    monkeypatch.setattr(service, '_own_profile', lambda *, user_id: facility)
    monkeypatch.setattr(service.matches, 'get_confirmed_for_record', lambda record_id: SimpleNamespace(
        confirmed_facility_id=facility.id, processing_method='TREAT'))
    monkeypatch.setattr(eligibility, 'eligible_facility', lambda database, profile: True)
    monkeypatch.setattr(eligibility, 'can_profile_action', lambda *args: True)
    published = []
    monkeypatch.setattr(tracking_manager, 'broadcast_from_sync', lambda payload, topics: published.append(payload))

    response = service.confirm_receipt(user_id=actor_id, record_id=records[0].id,
                                       received_quantity=Decimal('1.0'))
    assert response.waste_record_id == records[0].id
    db.expire_all()
    assert db.get(WasteRecord, records[0].id).status == WasteStatus.DESTINATION_RECEIVED
    assert db.get(PickupRequest, pickups[0].id).status == PickupStatus.COMPLETED
    assert db.get(Route, route.id).status == RouteStatus.COMPLETED
    assert db.get(Vehicle, vehicle.id).status == VehicleStatus.AVAILABLE
    assert any(event.get('event') == 'pickup.status.updated' and
               event.get('pickup_id') == str(pickups[0].id) and
               event.get('pickup_status') == PickupStatus.COMPLETED.value
               for event in published)
    assert any(event.get('event') == 'route.completed' for event in published)
    assert any(event.get('event') == 'destination.received' for event in published)


def test_full_receipt_multi_batch_does_not_complete_early(db, monkeypatch):
    from app.realtime.tracking_manager import tracking_manager
    import app.services.organization_eligibility as eligibility

    route, vehicle, pickups, records, _, _ = setup_route(db)
    extra = WasteRecord(id=uuid4(), waste_code=f'MW-ISSUE1-{uuid4().hex[:8]}',
                        hospital_id=pickups[0].hospital_id, category_id=uuid4(),
                        quantity=Decimal('3'), unit=WasteUnit.KG, status=WasteStatus.IN_TRANSIT,
                        generated_at=datetime.now(timezone.utc))
    pickups[0].items.append(PickupRequestItem(waste_record=extra))
    db.add(extra)
    db.commit()
    facility = SimpleNamespace(id=uuid4(), name='Demo Treatment Facility')
    service = ReceivingService(db)
    monkeypatch.setattr(service, '_own_profile', lambda *, user_id: facility)
    monkeypatch.setattr(service.matches, 'get_confirmed_for_record', lambda record_id: SimpleNamespace(
        confirmed_facility_id=facility.id, processing_method='TREAT'))
    monkeypatch.setattr(eligibility, 'eligible_facility', lambda database, profile: True)
    monkeypatch.setattr(eligibility, 'can_profile_action', lambda *args: True)
    published = []
    monkeypatch.setattr(tracking_manager, 'broadcast_from_sync', lambda payload, topics: published.append(payload))
    actor = uuid4()
    service.confirm_receipt(user_id=actor, record_id=records[0].id, received_quantity=Decimal('1'))
    assert db.get(PickupRequest, pickups[0].id).status == PickupStatus.IN_TRANSIT
    assert db.get(Route, route.id).status == RouteStatus.ACTIVE
    assert not any(event.get('event') == 'pickup.status.updated' for event in published)
    service.confirm_receipt(user_id=actor, record_id=extra.id, received_quantity=Decimal('3'))
    db.expire_all()
    assert db.get(PickupRequest, pickups[0].id).status == PickupStatus.COMPLETED
    assert db.get(Route, route.id).status == RouteStatus.COMPLETED
    assert len([e for e in published if e.get('event') == 'pickup.status.updated']) == 1
