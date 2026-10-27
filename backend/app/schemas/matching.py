import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.waste_enums import DestinationType


class MatchCandidateResponse(BaseModel):
    id: uuid.UUID
    name: str
    city: str
    score: int
    is_verified: bool
    reasons: list[str]
    processing_method: str | None = None


class MatchConfirmRequest(BaseModel):
    destination_id: uuid.UUID | None = Field(
        default=None,
        description="Which candidate to confirm. Omit to confirm the top-ranked recommendation.",
    )


class MatchingRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    waste_record_id: uuid.UUID
    destination_type: DestinationType
    candidates: list[MatchCandidateResponse]
    explanation: str
    processing_method: str | None
    routing_status: str
    routing_reason: str | None
    decision_method: str
    match_score: float | None
    requires_human_verification: bool
    confirmed_facility_id: uuid.UUID | None
    is_confirmed: bool
    confirmed_by: uuid.UUID | None
    confirmed_at: datetime | None
    created_at: datetime
