import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.roles import UserRole
from app.models.waste_enums import WasteEventType, WasteStatus


class EventActorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    role: UserRole


class WasteEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    waste_record_id: uuid.UUID
    event_type: WasteEventType
    status_snapshot: WasteStatus
    actor: EventActorResponse | None
    quantity: Decimal | None
    notes: str | None
    event_metadata: dict
    created_at: datetime
