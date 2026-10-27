from app.services.gps_simulator_service import _bearing, _path_lengths, _point_at_distance


def test_bearing_is_normalized():
    heading = _bearing((89.5, 22.8), (89.6, 22.8))
    assert 0 <= heading < 360


def test_interpolation_clamps_to_route_end():
    points = [(89.5, 22.8), (89.6, 22.8)]
    lengths = _path_lengths(points)
    lat, lon, _ = _point_at_distance(points, lengths, 999)
    assert lat == 22.8
    assert lon == 89.6
