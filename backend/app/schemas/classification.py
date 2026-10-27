import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.waste_enums import ClassificationConfidence, ClassificationSource
from app.schemas.waste import WasteCategoryResponse


class RuleMatchResponse(BaseModel):
    category_code: str
    matched_keywords: list[str]


class ManualClassificationRequest(BaseModel):
    category_id: uuid.UUID
    notes: str | None = Field(default=None, max_length=1000)


class WasteClassificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    waste_record_id: uuid.UUID
    suggested_category: WasteCategoryResponse
    source: ClassificationSource
    confidence: ClassificationConfidence
    matched_rules: list[RuleMatchResponse]
    explanation: str
    notes: str | None
    is_confirmed: bool
    confirmed_by: uuid.UUID | None
    confirmed_at: datetime | None
    created_at: datetime
