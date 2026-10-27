import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.pickup_request import PickupRequest, PickupRequestItem
from app.models.waste_enums import PickupStatus
from app.models.waste_record import WasteRecord


class PickupRequestRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, pickup: PickupRequest) -> PickupRequest:
        self.db.add(pickup)
        self.db.commit()
        self.db.refresh(pickup)
        return pickup

    def add_item(self, pickup_id: uuid.UUID, waste_record_id: uuid.UUID) -> None:
        self.db.add(PickupRequestItem(pickup_request_id=pickup_id, waste_record_id=waste_record_id))

    def get_by_id_for_hospital(
        self, *, pickup_id: uuid.UUID, hospital_id: uuid.UUID
    ) -> PickupRequest | None:
        stmt = (
            select(PickupRequest)
            .options(selectinload(PickupRequest.items).selectinload(PickupRequestItem.waste_record))
            .where(PickupRequest.id == pickup_id, PickupRequest.hospital_id == hospital_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_id(self, pickup_id: uuid.UUID) -> PickupRequest | None:
        stmt = (
            select(PickupRequest)
            .options(selectinload(PickupRequest.items).selectinload(PickupRequestItem.waste_record))
            .where(PickupRequest.id == pickup_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def search_for_hospital(
        self, *, hospital_id: uuid.UUID, page: int, page_size: int, status: PickupStatus | None
    ) -> tuple[list[PickupRequest], int]:
        conditions = [PickupRequest.hospital_id == hospital_id]
        if status is not None:
            conditions.append(PickupRequest.status == status)

        total = self.db.execute(
            select(func.count()).select_from(PickupRequest).where(*conditions)
        ).scalar_one()

        stmt = (
            select(PickupRequest)
            .options(selectinload(PickupRequest.items).selectinload(PickupRequestItem.waste_record))
            .where(*conditions)
            .order_by(PickupRequest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(self.db.execute(stmt).scalars().all())
        return items, total

    def list_assigned_to_collector(self, collector_id: uuid.UUID) -> list[PickupRequest]:
        stmt = (
            select(PickupRequest)
            .options(selectinload(PickupRequest.items).selectinload(PickupRequestItem.waste_record))
            .where(
                PickupRequest.assigned_collector_id == collector_id,
                PickupRequest.status.in_(
                    [PickupStatus.ASSIGNED, PickupStatus.COLLECTED, PickupStatus.IN_TRANSIT]
                ),
            )
            .order_by(PickupRequest.scheduled_at)
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_active_pickup_for_waste_record(self, waste_record_id: uuid.UUID) -> PickupRequest | None:
        stmt = (
            select(PickupRequest)
            .join(PickupRequestItem)
            .where(
                PickupRequestItem.waste_record_id == waste_record_id,
                PickupRequest.status.in_([PickupStatus.REQUESTED, PickupStatus.ASSIGNED]),
            )
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def save(self, pickup: PickupRequest, *, commit: bool = True) -> PickupRequest:
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(pickup)
        return pickup
