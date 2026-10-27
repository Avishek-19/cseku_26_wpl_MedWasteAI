import uuid

from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from app.models.route import Route, RouteStop, RouteStatus


class RouteRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, route: Route, stops: list[RouteStop]) -> Route:
        self.db.add(route)
        self.db.flush()
        for stop in stops:
            stop.route_id = route.id
            self.db.add(stop)
        self.db.commit()
        return route

    def next_version_for_vehicle(self, vehicle_id: uuid.UUID) -> int:
        stmt = select(func.coalesce(func.max(Route.version), 0) + 1).where(Route.vehicle_id == vehicle_id)
        return int(self.db.execute(stmt).scalar_one())

    def get_active_for_vehicle(self, vehicle_id: uuid.UUID) -> Route | None:
        stmt = (
            select(Route)
            .where(Route.vehicle_id == vehicle_id, Route.status == RouteStatus.ACTIVE)
            .order_by(desc(Route.version))
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_id(self, route_id: uuid.UUID) -> Route | None:
        return self.db.get(Route, route_id)

    def list_stops(self, route_id: uuid.UUID) -> list[RouteStop]:
        stmt = select(RouteStop).where(RouteStop.route_id == route_id).order_by(RouteStop.sequence)
        return list(self.db.execute(stmt).scalars().all())

    def list_for_vehicle(self, vehicle_id: uuid.UUID) -> list[Route]:
        stmt = select(Route).where(Route.vehicle_id == vehicle_id).order_by(Route.version.desc())
        return list(self.db.execute(stmt).scalars().all())
