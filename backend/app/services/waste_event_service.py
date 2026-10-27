import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.waste_enums import WasteEventType, WasteStatus
from app.models.waste_event import WasteEvent
from app.repositories.waste_event_repository import WasteEventRepository


class WasteEventService:
    def __init__(self, db: Session):
        self.db = db
        self.events = WasteEventRepository(db)

    def record(
        self,
        *,
        waste_record_id: uuid.UUID,
        event_type: WasteEventType,
        status_snapshot: WasteStatus,
        actor_user_id: uuid.UUID | None,
        quantity: Decimal | None = None,
        notes: str | None = None,
        metadata: dict | None = None,
        commit: bool = True,
    ) -> WasteEvent:
        event = WasteEvent(
            waste_record_id=waste_record_id,
            event_type=event_type,
            status_snapshot=status_snapshot,
            actor_user_id=actor_user_id,
            quantity=quantity,
            notes=notes,
            event_metadata=metadata or {},
        )
        return self.events.create(event, commit=commit)

    def list_timeline(self, waste_record_id: uuid.UUID) -> list[WasteEvent]:
        return self.events.list_for_record(waste_record_id)
