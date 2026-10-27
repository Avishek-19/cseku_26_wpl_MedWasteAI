"""Issue 2: hospital pickup windows are hard ETA constraints in optimization and replanning.

Run from backend:
  DATABASE_URL=sqlite+pysqlite:///:memory: python -m pytest -q unit_tests/test_issue2_pickup_windows.py
No external OSRM or real PostgreSQL instance is required for this targeted suite.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.core.config import Settings
from app.core.db import Base
from app.models.pickup_request import PickupRequest
from app.models.route import Route, RouteStatus, RouteStop, RouteStopStatus
from app.models.vehicle import Vehicle
from app.models.waste_enums import PickupPriority, PickupStatus, VehicleStatus
from app.services.route_optimization_service import (
    Point, RouteOptimizationService, RouteValidationError,
)


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as db:
        service = RouteOptimizationService(db, Settings(routing_provider="haversine", route_max_duration_minutes=240))
        monkeypatch.setattr(service, "_can_manage", lambda user, vehicle: True)
        monkeypatch.setattr(service, "_weight", lambda pickup: 3.0)
        monkeypatch.setattr(service, "_destination", lambda pickups, latitude, longitude: Point(0, .012))
        monkeypatch.setattr(service, "_stop_point", lambda pickup, explicit: explicit[pickup.id])
        monkeypatch.setattr(service, "_validate_dispatch_destination", lambda pickups: None)
        vehicle = Vehicle(id=uuid4(), vehicle_code=f"WINDOW-{uuid4().hex[:9]}",
                          assigned_collector_id=uuid4(), capacity_kg=Decimal("250"),
                          status=VehicleStatus.RESERVED, is_active=True)
        db.add(vehicle)
        db.commit()
        yield db, service, vehicle
    engine.dispose()


def make_pickup(db, vehicle, *, earliest=None, latest=None, priority=PickupPriority.NORMAL):
    pickup = PickupRequest(
        id=uuid4(), hospital_id=uuid4(), priority=priority, status=PickupStatus.ASSIGNED,
        requested_pickup_at=earliest, requested_pickup_end_at=latest,
        assigned_vehicle_id=vehicle.id, assigned_collector_id=vehicle.assigned_collector_id,
    )
    db.add(pickup)
    db.commit()
    return pickup


def plan(service, vehicle, pickups, points, start):
    return service.optimize(
        user=None, vehicle_id=vehicle.id, pickup_ids=[p.id for p in pickups],
        origin_latitude=Decimal('0'), origin_longitude=Decimal('0'),
        stop_coordinates={p.id: point for p, point in zip(pickups, points)},
        start_at=start,
    )


def to_utc(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def test_provider_eta_is_accepted_at_or_before_deadline(env):
    db, service, vehicle = env
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    p = make_pickup(db, vehicle, earliest=start + timedelta(minutes=3),
                    latest=start + timedelta(minutes=3))
    result = plan(service, vehicle, [p], [Point(0, .003)], start)
    stop = db.scalar(select(RouteStop).where(RouteStop.route_id == result.id))
    assert to_utc(stop.estimated_arrival_at) == start + timedelta(minutes=3)
    assert result.estimated_duration_minutes >= 3
    assert result.optimization_details["constraints"]["requested_pickup_end_time"] is True


def test_beyond_deadline_is_rejected_before_writing_route(env):
    db, service, vehicle = env
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    p = make_pickup(db, vehicle, latest=start)  # 1+ minute road travel
    with pytest.raises(RouteValidationError, match="later than the deadline"):
        plan(service, vehicle, [p], [Point(0, .003)], start)
    assert db.scalars(select(Route)).all() == []


def test_end_only_window_is_enforced(env):
    db, service, vehicle = env
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    p = make_pickup(db, vehicle, latest=start + timedelta(minutes=1))
    route = plan(service, vehicle, [p], [Point(0, .003)], start)
    stop = db.scalar(select(RouteStop).where(RouteStop.route_id == route.id))
    assert to_utc(stop.estimated_arrival_at) <= to_utc(p.requested_pickup_end_at)


def test_invalid_window_end_before_start_is_rejected(env):
    db, service, vehicle = env
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    p = make_pickup(db, vehicle, earliest=start + timedelta(minutes=4),
                    latest=start + timedelta(minutes=3))
    with pytest.raises(RouteValidationError, match="end before start"):
        plan(service, vehicle, [p], [Point(0, .003)], start)


def test_deadline_first_within_same_priority_and_timezone_offsets(env):
    db, service, vehicle = env
    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=2)
    # Offset-aware input must compare against the UTC arrival correctly.
    early = make_pickup(db, vehicle, latest=(start + timedelta(minutes=2)).astimezone(
        timezone(timedelta(hours=6))))
    late = make_pickup(db, vehicle, latest=start + timedelta(minutes=6))
    result = plan(service, vehicle, [late, early], [Point(0, .006), Point(0, .003)], start)
    stops = sorted(db.scalars(select(RouteStop).where(RouteStop.route_id == result.id)).all(),
                   key=lambda x: x.sequence)
    assert [s.pickup_id for s in stops] == [early.id, late.id]
    assert to_utc(stops[0].estimated_arrival_at) <= start + timedelta(minutes=2)
    assert to_utc(stops[1].estimated_arrival_at) <= start + timedelta(minutes=6)


def test_waiting_for_first_pickup_cannot_silently_make_second_one_late(env):
    db, service, vehicle = env
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    first = make_pickup(db, vehicle, earliest=start + timedelta(minutes=10))
    second = make_pickup(db, vehicle, latest=start + timedelta(minutes=4))
    # The bounded pickup is planned first even though the caller provided the
    # flexible one first. Both can now be serviced within their constraints.
    result = plan(service, vehicle, [first, second], [Point(0, .003), Point(0, .006)], start)
    stops = sorted(db.scalars(select(RouteStop).where(RouteStop.route_id == result.id)).all(),
                   key=lambda x: x.sequence)
    assert stops[0].pickup_id == second.id
    assert to_utc(stops[0].estimated_arrival_at) <= to_utc(second.requested_pickup_end_at)
    assert to_utc(stops[1].estimated_arrival_at) >= to_utc(first.requested_pickup_at)
    assert result.estimated_duration_minutes >= 10


def test_failed_new_plan_does_not_cancel_existing_draft(env):
    db, service, vehicle = env
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    p1 = make_pickup(db, vehicle)
    old = plan(service, vehicle, [p1], [Point(0, .003)], start)
    # A new pickup can be assigned after an existing route draft was saved.
    # The planner now requires the complete assigned set, even for drafts.
    p2 = make_pickup(db, vehicle, latest=start)  # impossible
    with pytest.raises(RouteValidationError, match="deadline"):
        plan(service, vehicle, [p1, p2], [Point(0, .003), Point(0, .006)], start)
    db.expire_all()
    assert db.get(Route, old.id).status == RouteStatus.DRAFT
    assert len(db.scalars(select(Route)).all()) == 1


def test_cached_optimization_cannot_reuse_route_after_window_changes(env):
    db, service, vehicle = env
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    p = make_pickup(db, vehicle)
    route = plan(service, vehicle, [p], [Point(0, .003)], start)
    p.requested_pickup_end_at = start
    db.commit()
    # Issue 4 recalculates changed input instead of returning an old cached
    # route. The newly calculated arrival must still fail the same hard window.
    with pytest.raises(RouteValidationError, match="later than the deadline"):
        plan(service, vehicle, [p], [Point(0, .003)], start)
    db.expire_all()
    assert db.get(Route, route.id).status == RouteStatus.DRAFT


def test_confirmation_rejects_new_deadline_that_invalidates_eta(env):
    db, service, vehicle = env
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    p = make_pickup(db, vehicle)
    route = plan(service, vehicle, [p], [Point(0, .003)], start)
    p.requested_pickup_end_at = start
    db.commit()
    with pytest.raises(RouteValidationError, match="ETA exceeds"):
        service.confirm(user=None, route_id=route.id)
    db.expire_all()
    assert db.get(Route, route.id).status == RouteStatus.DRAFT


def make_active_route(db, vehicle, *, pickups, points):
    route = Route(id=uuid4(), status=RouteStatus.ACTIVE, vehicle_id=vehicle.id,
                  origin_latitude=Decimal('0'), origin_longitude=Decimal('0'),
                  destination_latitude=Decimal('0'), destination_longitude=Decimal('.012'),
                  is_optimized=True, version=1,
                  optimization_details={"algorithm": "priority_seeded_nearest_neighbor_2opt"})
    db.add(route)
    for i, (p, point) in enumerate(zip(pickups, points), start=1):
        db.add(RouteStop(route_id=route.id, pickup_id=p.id, sequence=i,
                         latitude=Decimal(str(point.latitude)),
                         longitude=Decimal(str(point.longitude)), status=RouteStopStatus.PENDING))
    db.commit()
    return route


def test_active_recalculation_rejects_late_stop_without_mutation(env):
    db, service, vehicle = env
    now = datetime.now(timezone.utc)
    p1 = make_pickup(db, vehicle, latest=now + timedelta(minutes=1))
    p2 = make_pickup(db, vehicle, latest=now + timedelta(minutes=1))
    route = make_active_route(db, vehicle, pickups=[p1, p2], points=[Point(0, .003), Point(0, .009)])
    with pytest.raises(RouteValidationError, match="deadline"):
        service.recalculate_active(user=SimpleNamespace(id=uuid4()), route_id=route.id, reason="dispatcher requested recalculation")
    db.expire_all()
    persisted = db.get(Route, route.id)
    assert persisted.optimization_details == {"algorithm": "priority_seeded_nearest_neighbor_2opt"}
    assert [(s.sequence, s.estimated_arrival_at) for s in
            sorted(db.scalars(select(RouteStop).where(RouteStop.route_id == route.id)).all(),
                   key=lambda s: s.sequence)] == [(1, None), (2, None)]


def test_active_recalculation_writes_only_on_valid_schedule(env):
    db, service, vehicle = env
    now = datetime.now(timezone.utc)
    p1 = make_pickup(db, vehicle, latest=now + timedelta(minutes=20))
    p2 = make_pickup(db, vehicle, latest=now + timedelta(minutes=20))
    route = make_active_route(db, vehicle, pickups=[p1, p2], points=[Point(0, .003), Point(0, .006)])
    changed = service.recalculate_active(user=SimpleNamespace(id=uuid4()), route_id=route.id, reason="dispatcher requested recalculation")
    assert changed.id == route.id
    assert changed.optimization_details["remaining_duration_minutes"] > 0
    assert all(stop.estimated_arrival_at is not None for stop in
               db.scalars(select(RouteStop).where(RouteStop.route_id == route.id)).all())


def test_past_requested_route_start_does_not_bypass_expired_deadline(env):
    db, service, vehicle = env
    past = datetime.now(timezone.utc) - timedelta(hours=3)
    p = make_pickup(db, vehicle, latest=past + timedelta(minutes=5))
    with pytest.raises(RouteValidationError, match="later than the deadline"):
        plan(service, vehicle, [p], [Point(0, .003)], past)
    assert db.scalars(select(Route)).all() == []


def test_delayed_dispatch_is_rejected_if_deadline_would_be_missed(env):
    db, service, vehicle = env
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    p = make_pickup(db, vehicle, latest=start + timedelta(minutes=3))
    route = plan(service, vehicle, [p], [Point(0, .003)], start)
    stops = service.routes.list_stops(route.id)
    # One-minute initial ETA is within the deadline. If departure is postponed
    # 2.5 minutes (before the 3-minute deadline), the arrival would be late.
    with pytest.raises(RouteValidationError, match="departure delay"):
        service._validate_existing_windows(stops, [p], route=route,
                                           now=start + timedelta(minutes=2, seconds=30))
    service._validate_existing_windows(stops, [p], route=route, now=start)


def test_waiting_time_counts_against_max_route_duration(env):
    db, service, vehicle = env
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    service.settings.route_max_duration_minutes = 5
    p = make_pickup(db, vehicle, earliest=start + timedelta(minutes=10),
                    latest=start + timedelta(minutes=12))
    with pytest.raises(RouteValidationError, match="exceeds configured maximum"):
        plan(service, vehicle, [p], [Point(0, .003)], start)
    assert db.scalars(select(Route)).all() == []


def test_one_pending_stop_recalculation_enforces_deadline(env):
    db, service, vehicle = env
    now = datetime.now(timezone.utc)
    p = make_pickup(db, vehicle, latest=now)  # already closed
    route = make_active_route(db, vehicle, pickups=[p], points=[Point(0, .003)])
    with pytest.raises(RouteValidationError, match="deadline"):
        service.recalculate_active(user=SimpleNamespace(id=uuid4()), route_id=route.id,
                                   reason="dispatcher requests ETA correction")
    db.expire_all()
    assert db.get(Route, route.id).optimization_details == {
        "algorithm": "priority_seeded_nearest_neighbor_2opt"
    }


def test_windowed_route_confirms_starts_and_idempotently_reconfirms(env):
    db, service, vehicle = env
    start = datetime.now(timezone.utc) + timedelta(minutes=1)
    p = make_pickup(db, vehicle, latest=start + timedelta(minutes=30))
    route = plan(service, vehicle, [p], [Point(0, .003)], start)
    confirmed = service.confirm(user=None, route_id=route.id)
    assert confirmed.status == RouteStatus.READY
    assert service.confirm(user=None, route_id=route.id).status == RouteStatus.READY
    started = service.start(user=None, route_id=route.id)
    assert started.status == RouteStatus.ACTIVE
    assert db.scalar(select(RouteStop).where(RouteStop.route_id == route.id)).status == RouteStopStatus.EN_ROUTE


def test_reconfirmation_rejects_deadline_changed_since_ready(env):
    db, service, vehicle = env
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    p = make_pickup(db, vehicle, latest=start + timedelta(minutes=10))
    route = plan(service, vehicle, [p], [Point(0, .003)], start)
    service.confirm(user=None, route_id=route.id)
    p.requested_pickup_end_at = start
    db.commit()
    with pytest.raises(RouteValidationError, match="ETA exceeds"):
        service.confirm(user=None, route_id=route.id)
    db.expire_all()
    assert db.get(Route, route.id).status == RouteStatus.READY


def test_changed_departure_must_not_reuse_cached_windowed_route(env):
    db, service, vehicle = env
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    p = make_pickup(db, vehicle, latest=start + timedelta(minutes=5))
    original = plan(service, vehicle, [p], [Point(0, .003)], start)
    with pytest.raises(RouteValidationError, match="deadline"):
        plan(service, vehicle, [p], [Point(0, .003)], start + timedelta(minutes=10))
    db.expire_all()
    assert db.get(Route, original.id).status == RouteStatus.DRAFT
    assert len(db.scalars(select(Route)).all()) == 1
