"""Issue 4: explicit replans are fresh; only byte-identical resolved plans are cached.

The tests use the true optimize/recalculate API service against SQLite, with
external routing and authorization replaced by deterministic test fixtures.
PostgreSQL locking must be verified in a separate deployment integration run.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

# Route endpoint imports authentication's bcrypt module even though the tests
# never call auth. The isolated test environment can lack this optional binary
# dependency; use a test-only import stub, never in the application itself.
import importlib.util
import sys
from types import ModuleType
if importlib.util.find_spec('bcrypt') is None:
    sys.modules.setdefault('bcrypt', ModuleType('bcrypt'))

from app.api import routes as route_api
from app.models.route import Route, RouteStatus
from app.models.waste_enums import PickupPriority
from app.services.route_optimization_service import Point, RouteOptimizationService, RouteValidationError
from unit_tests.test_issue2_pickup_windows import env, make_pickup  # noqa: F401


def future():
    return datetime.now(timezone.utc) + timedelta(hours=2)


def select_route(service, vehicle, p, start, *, origin=(0, 0), point=Point(0, .003), **opts):
    return service.optimize(
        user=None, vehicle_id=vehicle.id, pickup_ids=[p.id],
        origin_latitude=Decimal(str(origin[0])), origin_longitude=Decimal(str(origin[1])),
        stop_coordinates={p.id: point}, start_at=start, **opts,
    )


def count_routes(db):
    return len(db.scalars(select(Route)).all())


def test_exact_same_future_plan_is_idempotent(env):
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    departure = future()
    original = select_route(service, vehicle, p, departure)
    repeat = select_route(service, vehicle, p, departure)
    assert repeat.id == original.id
    assert count_routes(db) == 1
    assert original.optimization_details['input_fingerprint_version'] == 1
    assert len(original.optimization_details['input_fingerprint']) == 64


def test_explicit_recalculation_supersedes_even_when_inputs_unchanged(env):
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    departure = future()
    original = select_route(service, vehicle, p, departure)
    rerouted = select_route(service, vehicle, p, departure, force_recalculate=True)
    assert original.id != rerouted.id
    assert rerouted.version == original.version + 1
    assert db.get(Route, original.id).status == RouteStatus.CANCELLED
    assert rerouted.status == RouteStatus.DRAFT
    assert count_routes(db) == 2


def test_changed_origin_generates_fresh_route(env):
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    departure = future()
    original = select_route(service, vehicle, p, departure)
    new = select_route(service, vehicle, p, departure, origin=(0, .001))
    assert new.id != original.id
    assert float(new.origin_longitude) == .001
    assert db.get(Route, original.id).status == RouteStatus.CANCELLED
    assert new.optimization_details['input_fingerprint'] != original.optimization_details['input_fingerprint']


def test_changed_stop_point_generates_fresh_route(env):
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    departure = future()
    original = select_route(service, vehicle, p, departure)
    new = select_route(service, vehicle, p, departure, point=Point(0, .007))
    assert new.id != original.id
    assert float(service.routes.list_stops(new.id)[0].longitude) == .007


def test_changed_destination_generates_fresh_route(env, monkeypatch):
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    departure = future()
    original = select_route(service, vehicle, p, departure)
    monkeypatch.setattr(service, '_destination', lambda pickups, latitude, longitude: Point(0, .025))
    new = select_route(service, vehicle, p, departure)
    assert new.id != original.id
    assert float(new.destination_longitude) == .025


def test_changed_departure_time_generates_fresh_eta(env):
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    departure = future()
    original = select_route(service, vehicle, p, departure)
    new = select_route(service, vehicle, p, departure + timedelta(minutes=10))
    assert new.id != original.id
    assert service.routes.list_stops(new.id)[0].estimated_arrival_at > service.routes.list_stops(original.id)[0].estimated_arrival_at


def test_changed_weight_or_priority_generates_fresh_route(env, monkeypatch):
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    departure = future()
    original = select_route(service, vehicle, p, departure)
    p.priority = PickupPriority.URGENT
    db.commit()
    updated_priority = select_route(service, vehicle, p, departure)
    assert updated_priority.id != original.id
    monkeypatch.setattr(service, '_weight', lambda pickup: 9.0)
    updated_weight = select_route(service, vehicle, p, departure)
    assert updated_weight.id != updated_priority.id
    assert updated_weight.optimization_details['total_load_kg'] == 9.0


def test_changed_deadline_recalculates_if_new_window_is_feasible(env):
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    departure = future()
    original = select_route(service, vehicle, p, departure)
    p.requested_pickup_end_at = departure + timedelta(minutes=4)
    db.commit()
    updated = select_route(service, vehicle, p, departure)
    assert updated.id != original.id
    assert db.get(Route, original.id).status == RouteStatus.CANCELLED
    assert updated.status == RouteStatus.DRAFT


def test_legacy_route_without_fingerprint_is_not_reused(env):
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    departure = future()
    original = select_route(service, vehicle, p, departure)
    details = dict(original.optimization_details)
    details.pop('input_fingerprint')
    original.optimization_details = details
    db.commit()
    new = select_route(service, vehicle, p, departure)
    assert new.id != original.id


def test_implicit_departure_recalculates_to_avoid_stale_etas(env):
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    kwargs = dict(user=None, vehicle_id=vehicle.id, pickup_ids=[p.id],
                  origin_latitude=Decimal('0'), origin_longitude=Decimal('0'),
                  stop_coordinates={p.id: Point(0, .003)})
    original = service.optimize(**kwargs)
    new = service.optimize(**kwargs)
    assert new.id != original.id
    assert new.version == original.version + 1


def test_changed_routing_speed_does_not_reuse_stale_duration(env):
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    departure = future()
    original = select_route(service, vehicle, p, departure)
    service.settings.routing_average_speed_kmh = 12.0
    new = select_route(service, vehicle, p, departure)
    assert new.id != original.id
    assert new.estimated_duration_minutes > original.estimated_duration_minutes


def test_recalculated_route_does_not_delete_old_on_failed_optimization(env):
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    departure = future()
    original = select_route(service, vehicle, p, departure)
    p.requested_pickup_end_at = departure
    db.commit()
    try:
        select_route(service, vehicle, p, departure, force_recalculate=True)
        assert False, 'Expected window rejection'
    except RouteValidationError as exc:
        assert 'deadline' in str(exc)
    db.expire_all()
    assert db.get(Route, original.id).status == RouteStatus.DRAFT
    assert count_routes(db) == 1


def test_http_recalculate_endpoint_forces_new_draft_for_ready_route(env, monkeypatch):
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    departure = future()
    old = select_route(service, vehicle, p, departure)
    old.status = RouteStatus.READY
    db.commit()
    monkeypatch.setattr(route_api, 'RouteOptimizationService', lambda db, settings: service)
    monkeypatch.setattr(route_api, '_response', lambda route, db: route)
    monkeypatch.setattr(route_api.tracking_manager, 'broadcast_from_sync', lambda *a, **kw: None)
    new = route_api.recalculate_route(route_id=old.id, current_user=None, db=db)
    assert new.id != old.id
    assert new.status == RouteStatus.DRAFT
    assert db.get(Route, old.id).status == RouteStatus.CANCELLED


def test_http_recalculate_preserves_old_route_on_invalid_deadline(env, monkeypatch):
    from fastapi import HTTPException
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    departure = future()
    old = select_route(service, vehicle, p, departure)
    # The recalc endpoint plans an immediate departure. Make the new deadline
    # impossible even for an immediate journey to verify atomic rejection.
    p.requested_pickup_end_at = datetime.now(timezone.utc)
    db.commit()
    monkeypatch.setattr(route_api, 'RouteOptimizationService', lambda db, settings: service)
    with __import__('pytest').raises(HTTPException) as exc:
        route_api.recalculate_route(route_id=old.id, current_user=None, db=db)
    assert exc.value.status_code == 422
    db.expire_all()
    assert db.get(Route, old.id).status == RouteStatus.DRAFT


def test_duplicate_pickup_ids_rejected_before_route_creation(env):
    import pytest
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    with pytest.raises(RouteValidationError, match="only appear once"):
        service.optimize(user=None, vehicle_id=vehicle.id,
                         pickup_ids=[p.id, p.id], start_at=future())
    assert count_routes(db) == 0


def test_cached_optimization_still_checks_facility_eligibility(env, monkeypatch):
    import pytest
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    departure = future()
    original = select_route(service, vehicle, p, departure)
    def suspended_facility(pickups):
        raise RouteValidationError("Confirmed facility no longer authorized")
    monkeypatch.setattr(service, '_validate_dispatch_destination', suspended_facility)
    with pytest.raises(RouteValidationError, match="no longer authorized"):
        select_route(service, vehicle, p, departure)
    assert db.get(Route, original.id).status == RouteStatus.DRAFT
    assert count_routes(db) == 1


def test_http_recalculate_does_not_revive_cancelled_or_completed_route(env, monkeypatch):
    import pytest
    from fastapi import HTTPException
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    original = select_route(service, vehicle, p, future())
    monkeypatch.setattr(route_api, 'RouteOptimizationService', lambda db, settings: service)
    for status in (RouteStatus.CANCELLED, RouteStatus.COMPLETED):
        original.status = status
        db.commit()
        with pytest.raises(HTTPException) as error:
            route_api.recalculate_route(route_id=original.id, current_user=None, db=db)
        assert error.value.status_code == 422
        assert count_routes(db) == 1


def test_http_recalculate_prefers_current_hospital_coordinates(env, monkeypatch):
    from uuid import uuid4
    from app.models.hospital_profile import HospitalProfile
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    original = select_route(service, vehicle, p, future())
    # The previous plan's saved location is now stale by >250 m.
    hospital = HospitalProfile(id=p.hospital_id, user_id=uuid4(),
        name='Hospital', registration_number='H001', contact_person='Manager',
        phone='01711111111', address_line='Road', city='Khulna', region='Khulna',
        postal_code='9000', latitude=Decimal('0'), longitude=Decimal('.009'))
    db.add(hospital)
    db.commit()
    # In the production optimizer _stop_point uses the verified profile. The
    # issue-2 fixture replaced _stop_point for pure ETA tests; remove that stub.
    monkeypatch.setattr(service, '_stop_point', RouteOptimizationService._stop_point.__get__(service))
    monkeypatch.setattr(route_api, 'RouteOptimizationService', lambda db, settings: service)
    monkeypatch.setattr(route_api, '_response', lambda route, db: route)
    monkeypatch.setattr(route_api.tracking_manager, 'broadcast_from_sync', lambda *a, **kw: None)
    changed = route_api.recalculate_route(route_id=original.id, current_user=None, db=db)
    assert changed.id != original.id
    assert float(service.routes.list_stops(changed.id)[0].longitude) == .009


def test_http_recalculate_prefers_current_facility_coordinates(env, monkeypatch):
    from uuid import uuid4
    from types import SimpleNamespace
    db, service, vehicle = env
    p = make_pickup(db, vehicle)
    original = select_route(service, vehicle, p, future())
    facility = SimpleNamespace(id=uuid4(), latitude=Decimal('0'), longitude=Decimal('.025'))
    monkeypatch.setattr(service, '_facility_for_pickup', lambda pickup: facility)
    # Assert stale destination coordinates are NOT sent to the resolver.
    def destination(pickups, latitude, longitude):
        assert latitude is None and longitude is None
        return Point(0, .025)
    monkeypatch.setattr(service, '_destination', destination)
    monkeypatch.setattr(route_api, 'RouteOptimizationService', lambda db, settings: service)
    monkeypatch.setattr(route_api, '_response', lambda route, db: route)
    monkeypatch.setattr(route_api.tracking_manager, 'broadcast_from_sync', lambda *a, **kw: None)
    changed = route_api.recalculate_route(route_id=original.id, current_user=None, db=db)
    assert changed.id != original.id
    assert float(changed.destination_longitude) == .025
