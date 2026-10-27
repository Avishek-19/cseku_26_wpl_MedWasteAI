from app.services.tracking_service import TrackingService


def test_route_progress_distance_is_zero_for_same_coordinate():
    assert TrackingService._distance_km(22.815, 89.55, 22.815, 89.55) == 0


def test_route_progress_distance_is_symmetric():
    first = TrackingService._distance_km(22.815, 89.55, 22.82, 89.56)
    second = TrackingService._distance_km(22.82, 89.56, 22.815, 89.55)
    assert first == second
    assert first > 0
