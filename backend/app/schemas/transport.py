import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.waste_enums import IncidentSeverity, IncidentType


class IncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    waste_record_id: uuid.UUID
    incident_type: IncidentType
    severity: IncidentSeverity
    description: str
    is_resolved: bool
    created_at: datetime


class ReceiveWasteRequest(BaseModel):
    demo_manual_receipt: bool = False
    received_quantity: Decimal | None = Field(
        default=None,
        gt=0,
        description="Measured weight at receipt. Defaults to the reported quantity if omitted.",
    )


class ReceiveWasteResponse(BaseModel):
    waste_record_id: uuid.UUID
    received_quantity: Decimal
    reported_quantity: Decimal
    variance_percent: Decimal
    incident: IncidentResponse | None