import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.waste_event import WasteEvent


class WasteEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, event: WasteEvent, *, commit: bool = True) -> WasteEvent:
        self.db.add(event)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(event)
        return event

    def list_for_record(self, waste_record_id: uuid.UUID) -> list[WasteEvent]:
        stmt = (
            select(WasteEvent)
            .options(selectinload(WasteEvent.actor))
            .where(WasteEvent.waste_record_id == waste_record_id)
            .order_by(WasteEvent.created_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())
