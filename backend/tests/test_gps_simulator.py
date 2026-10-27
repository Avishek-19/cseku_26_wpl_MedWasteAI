import asyncio
from types import SimpleNamespace

from app.services.gps_simulator_service import (
    _bearing,
    _path_lengths,
    _point_at_distance,
    _route_coordinates,
)


def test_route_geometry_is_preferred():
    route = SimpleNamespace(
        geometry={"type": "LineString", "coordinates": [[89.5, 22.8], [89.6, 22.9]]},
        origin_longitude=0,
        origin_latitude=0,
        destination_longitude=1,
        destination_latitude=1,
    )
    assert _route_coordinates(route, None) == [(89.5, 22.8), (89.6, 22.9)]


def test_point_interpolation_has_progressive_position_and_heading():
    points = [(89.5, 22.8), (89.6, 22.8)]
    lengths = _path_lengths(points)
    lat, lon, heading = _point_at_distance(points, lengths, lengths[-1] / 2)
    assert 22.79 < lat < 22.81
    assert 89.54 < lon < 89.56
    assert 89 <= heading <= 91
