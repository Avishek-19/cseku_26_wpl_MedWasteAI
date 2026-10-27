import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ProcessingStartRequest(BaseModel):
    processing_method: str = Field(min_length=1, max_length=80)


class ProcessingProofRequest(BaseModel):
    proof_note: str = Field(min_length=3, max_length=2000)


class ProcessingRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    waste_record_id: uuid.UUID
    facility_id: uuid.UUID
    processing_method: str
    status: str
    proof_note: str | None
    started_at: datetime | None
    proof_submitted_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
