"""Issue 5: arbitrary client destinations cannot substitute for saved facility GPS."""
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.services.route_optimization_service import Point, RouteOptimizationService, RouteValidationError


def setup_service(monkeypatch, facility):
    service = RouteOptimizationService(None, Settings(environment='development'))
    monkeypatch.setattr(service, '_facility_for_pickup', lambda pickup: facility)
    return service


@pytest.mark.parametrize('lat,lon', [(None, None), (None, 89.5), (22.8, None)])
def test_missing_facility_coordinates_reject_client_fallback_even_in_demo(monkeypatch, lat, lon):
    facility = SimpleNamespace(id=uuid4(), latitude=lat, longitude=lon)
    service = setup_service(monkeypatch, facility)
    with pytest.raises(RouteValidationError, match='no saved location'):
        service._destination([SimpleNamespace()], Decimal('23'), Decimal('90'))


def test_saved_facility_coordinate_is_authoritative(monkeypatch):
    facility = SimpleNamespace(id=uuid4(), latitude=Decimal('22.815000'), longitude=Decimal('89.550000'))
    service = setup_service(monkeypatch, facility)
    assert service._destination([SimpleNamespace()], None, None) == Point(22.815, 89.55)
    # A very near caller coordinate never overrides the saved destination.
    assert service._destination([SimpleNamespace()], Decimal('22.81510'), Decimal('89.55005')) == Point(22.815, 89.55)


def test_client_cannot_reroute_to_different_site(monkeypatch):
    facility = SimpleNamespace(id=uuid4(), latitude=Decimal('22.815'), longitude=Decimal('89.55'))
    service = setup_service(monkeypatch, facility)
    with pytest.raises(RouteValidationError, match='do not match'):
        service._destination([SimpleNamespace()], Decimal('22.9'), Decimal('89.9'))


@pytest.mark.parametrize('lat,lon', [(91, 89), (-91, 88), (20, 181), (float('nan'), 89), (22, float('inf'))])
def test_invalid_persisted_destination_coordinates_are_rejected(monkeypatch, lat, lon):
    facility = SimpleNamespace(id=uuid4(), latitude=lat, longitude=lon)
    service = setup_service(monkeypatch, facility)
    with pytest.raises(RouteValidationError, match='invalid saved GPS'):
        service._destination([SimpleNamespace()], None, None)


def test_partial_user_coordinates_are_rejected(monkeypatch):
    facility = SimpleNamespace(id=uuid4(), latitude=Decimal('22.815'), longitude=Decimal('89.55'))
    service = setup_service(monkeypatch, facility)
    with pytest.raises(RouteValidationError, match='both destination'):
        service._destination([SimpleNamespace()], Decimal('22.815'), None)


def test_multi_facility_pickups_not_allowed(monkeypatch):
    service = RouteOptimizationService(None, Settings(environment='development'))
    fac1, fac2 = SimpleNamespace(id=uuid4(), latitude=22.8, longitude=89.5), SimpleNamespace(id=uuid4(), latitude=22.9, longitude=89.6)
    monkeypatch.setattr(service, '_facility_for_pickup', lambda pickup: fac1 if pickup == 1 else fac2)
    with pytest.raises(RouteValidationError, match='different treatment facilities'):
        service._destination([1, 2], None, None)


def test_existing_saved_route_rejected_after_facility_moves_nearby(monkeypatch):
    facility = SimpleNamespace(id=uuid4(), latitude=Decimal('22.8156'), longitude=Decimal('89.5500'))
    service = setup_service(monkeypatch, facility)
    route = SimpleNamespace(destination_latitude=Decimal('22.8150'),
                            destination_longitude=Decimal('89.5500'))
    with pytest.raises(RouteValidationError, match='location changed'):
        service._require_current_route_destination(route, [SimpleNamespace()])


def test_saved_route_equal_to_current_facility_is_accepted(monkeypatch):
    facility = SimpleNamespace(id=uuid4(), latitude=Decimal('22.815'), longitude=Decimal('89.550'))
    service = setup_service(monkeypatch, facility)
    route = SimpleNamespace(destination_latitude=Decimal('22.815000'),
                            destination_longitude=Decimal('89.550000'))
    assert service._require_current_route_destination(route, [SimpleNamespace()]) == Point(22.815, 89.55)
