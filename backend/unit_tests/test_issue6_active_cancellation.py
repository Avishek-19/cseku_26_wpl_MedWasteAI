"""Issue 6: real PickupService cancellation + active route reconciliation."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.core.db import Base
from app.models.audit_log import AuditLog
from app.models.notification import Notification
from app.models.pickup_request import PickupRequest
from app.models.route import Route, RouteStatus, RouteStop, RouteStopStatus, RouteDestinationState
from app.models.tracking import TrackingSession, TrackingSessionStatus
from app.models.vehicle import Vehicle
from app.models.waste_enums import PickupStatus, VehicleStatus, WasteStatus
from app.services.pickup_service import PickupService, PickupNotCancellableError
from unit_tests.test_issue3_measured_collection_load import build_route


@pytest.fixture
def env(monkeypatch):
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as db:
        service = PickupService(db)
        # Hospital profile authorization is covered elsewhere; keep this suite
        # focused on route and physical handover atomicity.
        monkeypatch.setattr(service, 'get_pickup', lambda *, pickup_id, **kw: db.get(PickupRequest, pickup_id))
        monkeypatch.setattr(service.matches, 'get_confirmed_for_record', lambda record_id: None)
        yield db, service
    engine.dispose()


def setup(db, count=2, statuses=None, extra_job=False, tracked=False):
    weights = tuple((Decimal('5'), __import__('app.models.waste_enums', fromlist=['WasteUnit']).WasteUnit.KG) for _ in range(count))
    vehicle, route, pickups, _ = build_route(db, weights=weights, statuses=statuses)
    route.origin_latitude = Decimal('22.8')
    route.origin_longitude = Decimal('89.4')
    route.destination_latitude = Decimal('22.9')
    route.destination_longitude = Decimal('89.6')
    route.geometry = {'type': 'LineString', 'coordinates': [[89.4,22.8],[89.5,22.8],[89.6,22.9]]}
    route.optimization_details = {'existing': 'preserved'}
    session = None
    if tracked:
        session = TrackingSession(id=uuid4(), vehicle_id=vehicle.id,
                                  status=TrackingSessionStatus.ACTIVE, current_route_id=route.id)
        db.add(session)
        db.flush()
        route.tracking_session_id = session.id
    reserved = None
    if extra_job:
        from app.models.waste_enums import PickupPriority
        reserved = PickupRequest(id=uuid4(), hospital_id=uuid4(),
                                 priority=PickupPriority.NORMAL, status=PickupStatus.ASSIGNED,
                                 assigned_vehicle_id=vehicle.id)
        db.add(reserved)
    db.commit()
    return vehicle, route, pickups, session, reserved


def cancel(db, service, pickup, reason='Hospital appointment cancelled'):
    return service.cancel_pickup(user_id=uuid4(), pickup_id=pickup.id, reason=reason)


def find_stop(db, pickup):
    return db.scalar(select(RouteStop).where(RouteStop.pickup_id == pickup.id))


def test_cancel_enroute_advances_next_stop_and_notifies_driver(env):
    db, service = env
    vehicle, route, (p1,p2), tracking, _ = setup(db, statuses=[RouteStopStatus.EN_ROUTE, RouteStopStatus.PENDING], tracked=True)
    cancelled = cancel(db, service, p1)
    db.expire_all()
    assert cancelled.status == PickupStatus.CANCELLED
    assert find_stop(db, p1).status == RouteStopStatus.CANCELLED
    assert find_stop(db, p1).completed_at is not None
    assert find_stop(db, p2).status == RouteStopStatus.EN_ROUTE
    assert db.get(Route, route.id).status == RouteStatus.ACTIVE
    assert db.get(Vehicle, vehicle.id).status == VehicleStatus.ON_ROUTE
    assert db.get(Route, route.id).geometry is None
    assert db.get(Route, route.id).optimization_details['remaining_stop_count'] == 1
    assert db.get(Route, route.id).optimization_details['route_replan_required'] is True
    assert db.get(TrackingSession, tracking.id).status == TrackingSessionStatus.ACTIVE
    assert db.scalars(select(Notification).where(Notification.user_id == vehicle.assigned_collector_id)).all()
    assert db.scalars(select(AuditLog).where(AuditLog.action == 'pickup.cancel.active_route')).all()
    assert all(i.waste_record.status == WasteStatus.RISK_ASSESSED for i in cancelled.items)


def test_cancel_pending_does_not_advance_duplicate_stop(env):
    db, svc = env
    vehicle, route, (p1,p2), *_ = setup(db, statuses=[RouteStopStatus.EN_ROUTE, RouteStopStatus.PENDING])
    cancel(db, svc, p2)
    assert find_stop(db, p1).status == RouteStopStatus.EN_ROUTE
    assert find_stop(db, p2).status == RouteStopStatus.CANCELLED
    assert route.status == RouteStatus.ACTIVE


def test_cancel_arrived_stop_is_allowed_only_before_handover(env):
    db, svc = env
    v, route, (p1,p2), *_ = setup(db, statuses=[RouteStopStatus.ARRIVED, RouteStopStatus.PENDING])
    cancel(db, svc, p1)
    assert find_stop(db, p2).status == RouteStopStatus.EN_ROUTE
    assert find_stop(db, p1).status == RouteStopStatus.CANCELLED


def test_last_stop_no_waste_ends_route_tracking_and_releases_vehicle(env):
    db, svc = env
    vehicle, route, (pickup,), tracking, _ = setup(db, count=1, statuses=[RouteStopStatus.EN_ROUTE], tracked=True)
    cancel(db, svc, pickup)
    db.expire_all()
    assert db.get(Route, route.id).status == RouteStatus.CANCELLED
    assert db.get(Vehicle, vehicle.id).status == VehicleStatus.AVAILABLE
    saved_tracking = db.get(TrackingSession, tracking.id)
    assert saved_tracking.status == TrackingSessionStatus.CANCELLED
    assert saved_tracking.ended_at is not None
    assert saved_tracking.current_route_id is None
    assert db.get(Route, route.id).optimization_details['remaining_stop_count'] == 0


def test_last_stop_with_other_assigned_job_keeps_vehicle_reserved(env):
    db, svc = env
    vehicle, route, (pickup,), tracking, other = setup(db, count=1, statuses=[RouteStopStatus.EN_ROUTE], tracked=True, extra_job=True)
    cancel(db, svc, pickup)
    assert db.get(Vehicle, vehicle.id).status == VehicleStatus.RESERVED
    assert db.get(PickupRequest, other.id).status == PickupStatus.ASSIGNED


def test_cancel_last_uncollected_stop_after_another_collected_goes_to_facility(env):
    db, svc = env
    vehicle, route, (collected, pickup), tracking, _ = setup(db, statuses=[RouteStopStatus.COLLECTED, RouteStopStatus.EN_ROUTE], tracked=True)
    collected.status = PickupStatus.COLLECTED
    db.commit()
    cancel(db, svc, pickup)
    assert db.get(Route, route.id).status == RouteStatus.ACTIVE
    assert db.get(Route, route.id).destination_state == RouteDestinationState.EN_ROUTE_TO_DESTINATION.value
    assert db.get(Vehicle, vehicle.id).status == VehicleStatus.ON_ROUTE
    assert db.get(TrackingSession, tracking.id).status == TrackingSessionStatus.ACTIVE


def test_cannot_cancel_collected_route_stop_even_if_pickup_status_is_stale(env):
    db, svc = env
    vehicle, route, (p,), *_ = setup(db, count=1, statuses=[RouteStopStatus.COLLECTED])
    with pytest.raises(PickupNotCancellableError):
        cancel(db, svc, p)
    db.expire_all()
    assert db.get(PickupRequest, p.id).status == PickupStatus.ASSIGNED
    assert db.get(Route, route.id).status == RouteStatus.ACTIVE


def test_rollback_restores_route_stop_pickup_and_vehicle(env):
    db, svc = env
    vehicle, route, (p1,p2), *_ = setup(db, statuses=[RouteStopStatus.EN_ROUTE, RouteStopStatus.PENDING])
    # Service commit is intercepted after modifications to simulate DB failure.
    def aborted_commit():
        db.flush()
        raise RuntimeError('database commit failed')
    db.commit = aborted_commit
    with pytest.raises(RuntimeError, match='database commit failed'):
        cancel(db, svc, p1)
    db.rollback(); db.expire_all()
    assert db.get(PickupRequest, p1.id).status == PickupStatus.ASSIGNED
    assert find_stop(db, p1).status == RouteStopStatus.EN_ROUTE
    assert find_stop(db, p2).status == RouteStopStatus.PENDING
    assert db.get(Route, route.id).status == RouteStatus.ACTIVE


def test_simulator_fallback_path_omits_cancelled_and_collected_stops(env):
    from app.services.gps_simulator_service import _route_coordinates
    db, svc = env
    vehicle, route, (collected, cancelled, remaining), *_ = setup(
        db, count=3, statuses=[RouteStopStatus.COLLECTED,
                               RouteStopStatus.EN_ROUTE, RouteStopStatus.PENDING])
    collected.status = PickupStatus.COLLECTED
    find_stop(db, cancelled).longitude = Decimal('89.51')
    find_stop(db, remaining).longitude = Decimal('89.52')
    db.commit()
    cancel(db, svc, cancelled)
    coords = _route_coordinates(db.get(Route, route.id), db)
    assert len(coords) == 3  # re-based origin, remaining hospital, facility
    assert coords[1] == (float(find_stop(db, remaining).longitude), float(find_stop(db, remaining).latitude))
    assert (float(find_stop(db, cancelled).longitude),float(find_stop(db, cancelled).latitude)) not in coords[1:-1]
