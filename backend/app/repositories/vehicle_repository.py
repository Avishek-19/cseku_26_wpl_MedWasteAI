import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.vehicle import Vehicle
from app.models.waste_enums import VehicleStatus


class VehicleRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, vehicle: Vehicle) -> Vehicle:
        self.db.add(vehicle)
        self.db.commit()
        self.db.refresh(vehicle)
        return vehicle

    def get_by_code(self, vehicle_code: str) -> Vehicle | None:
        stmt = select(Vehicle).where(Vehicle.vehicle_code == vehicle_code)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_id(self, vehicle_id: uuid.UUID) -> Vehicle | None:
        return self.db.get(Vehicle, vehicle_id)

    def list_for_collector(self, collector_id: uuid.UUID) -> list[Vehicle]:
        stmt = select(Vehicle).where(Vehicle.assigned_collector_id == collector_id).order_by(
            Vehicle.vehicle_code
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_available(self) -> list[Vehicle]:
        stmt = select(Vehicle).where(
            Vehicle.status == VehicleStatus.AVAILABLE, Vehicle.is_active.is_(True)
        )
        return list(self.db.execute(stmt).scalars().all())

    def update(self, vehicle: Vehicle) -> Vehicle:
        self.db.commit()
        self.db.refresh(vehicle)
        return vehicle
