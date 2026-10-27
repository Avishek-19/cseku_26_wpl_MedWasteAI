from app.services.route_optimization_service import HaversineRoutingProvider, Point, RouteOptimizationService, StopCandidate
from app.models.waste_enums import PickupPriority


def test_haversine_distance_is_symmetric():
    provider = HaversineRoutingProvider(35)
    a, b = Point(22.815, 89.55), Point(22.82, 89.56)
    assert provider.distance(a, b) == provider.distance(b, a)
    assert provider.distance(a, b) > 0


def test_priority_constraint_survives_two_opt():
    candidates = [
        StopCandidate(None, Point(0, 0), 1, PickupPriority.EMERGENCY, None),
        StopCandidate(None, Point(0, 1), 1, PickupPriority.NORMAL, None),
        StopCandidate(None, Point(1, 0), 1, PickupPriority.URGENT, None),
    ]
    matrix = [
        [0, 1, 1, 2, 3],
        [1, 0, 2, 1, 2],
        [1, 2, 0, 1, 2],
        [2, 1, 1, 0, 1],
        [3, 2, 2, 1, 0],
    ]
    order = RouteOptimizationService._two_opt([0, 1, 3, 2, 4], matrix, candidates)
    priorities = [candidates[i - 1].priority for i in order[1:-1]]
    assert priorities == [PickupPriority.EMERGENCY, PickupPriority.URGENT, PickupPriority.NORMAL]
