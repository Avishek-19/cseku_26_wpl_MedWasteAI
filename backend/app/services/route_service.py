import uuid

from sqlalchemy.orm import Session

from app.models.route import Route, RouteStatus, RouteStop
from app.models.roles import UserRole
from app.models.user import User
from app.models.vehicle import Vehicle
from app.repositories.route_repository import RouteRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.route import RouteCreate


class RouteForbiddenError(Exception):
    pass


class RouteValidationError(Exception):
    pass


class RouteService:
    """Route persistence foundation. Optimization is intentionally deferred to Phase 3."""

    def __init__(self, db: Session):
        self.db = db
        self.routes = RouteRepository(db)
        self.vehicles = VehicleRepository(db)

    def create_draft(self, *, user: User, data: RouteCreate) -> Route:
        vehicle = self.vehicles.get_by_id(data.vehicle_id)
        if vehicle is None:
            raise RouteValidationError("Vehicle not found.")
        from app.services.route_optimization_service import RouteOptimizationService
        from app.core.config import get_settings
        if not RouteOptimizationService(self.db, get_settings())._can_manage(user, vehicle):
            raise RouteForbiddenError()
        sequences = [stop.sequence for stop in data.stops]
        if len(sequences) != len(set(sequences)):
            raise RouteValidationError("Route stop sequences must be unique.")

        route = Route(
            vehicle_id=vehicle.id,
            tracking_session_id=data.tracking_session_id,
            status=RouteStatus.DRAFT,
            version=1,
        )
        stops = [
            RouteStop(
                route_id=route.id,
                pickup_id=stop.pickup_id,
                sequence=stop.sequence,
                latitude=stop.latitude,
                longitude=stop.longitude,
            )
            for stop in data.stops
        ]
        route = self.routes.create(route, stops)
        return route
