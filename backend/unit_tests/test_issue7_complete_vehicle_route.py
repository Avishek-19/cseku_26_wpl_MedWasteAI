"""Issue 7: no successful draft can contain only some of a vehicle's assigned jobs."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select
import pytest
from app.models.route import Route, RouteStatus
from app.models.waste_enums import PickupStatus
from app.services.route_optimization_service import Point, RouteValidationError
from unit_tests.test_issue2_pickup_windows import env, make_pickup, plan  # noqa: F401


def test_optimizing_subset_is_rejected_before_any_draft(env):
    db, service, vehicle = env
    one, two = make_pickup(db, vehicle), make_pickup(db, vehicle)
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    with pytest.raises(RouteValidationError, match='Select every ASSIGNED pickup'):
        plan(service, vehicle, [one], [Point(0, .003)], start)
    assert not db.scalars(select(Route)).all()


def test_all_vehicle_assignments_produce_a_confirmable_route(env):
    db, service, vehicle = env
    one, two = make_pickup(db, vehicle), make_pickup(db, vehicle)
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    route = plan(service, vehicle, [one, two], [Point(0, .003), Point(0, .006)], start)
    assert route.status == RouteStatus.DRAFT
    assert {s.pickup_id for s in service.routes.list_stops(route.id)} == {one.id, two.id}
    # Existing backend confirmation checks are the second line of defense.
    assert service.confirm(user=None, route_id=route.id).status == RouteStatus.READY


def test_new_vehicle_assignment_invalidates_old_selection_without_cancelling_old_draft(env):
    db, service, vehicle = env
    one = make_pickup(db, vehicle)
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    old = plan(service, vehicle, [one], [Point(0, .003)], start)
    two = make_pickup(db, vehicle)
    with pytest.raises(RouteValidationError, match='Select every ASSIGNED pickup'):
        plan(service, vehicle, [one], [Point(0, .003)], start)
    assert db.get(Route, old.id).status == RouteStatus.DRAFT
    with pytest.raises(RouteValidationError, match='Vehicle pickup set changed'):
        service.confirm(user=None, route_id=old.id)
    updated = plan(service, vehicle, [one, two], [Point(0, .003), Point(0, .006)], start)
    assert updated.id != old.id
    assert db.get(Route, old.id).status == RouteStatus.CANCELLED


def test_collected_pickup_cannot_be_reintroduced_in_new_draft(env):
    db, service, vehicle = env
    collected = make_pickup(db, vehicle)
    pending = make_pickup(db, vehicle)
    collected.status = PickupStatus.COLLECTED
    db.commit()
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    with pytest.raises(RouteValidationError, match='Select every ASSIGNED pickup'):
        plan(service, vehicle, [collected, pending], [Point(0, .003), Point(0, .006)], start)
    assert not db.scalars(select(Route)).all()


def test_no_assigned_pickups_cannot_create_draft(env):
    db, service, vehicle = env
    old = make_pickup(db, vehicle)
    old.status = PickupStatus.CANCELLED
    db.commit()
    with pytest.raises(RouteValidationError, match='Select every ASSIGNED pickup'):
        plan(service, vehicle, [old], [Point(0, .003)], datetime.now(timezone.utc) + timedelta(hours=1))
