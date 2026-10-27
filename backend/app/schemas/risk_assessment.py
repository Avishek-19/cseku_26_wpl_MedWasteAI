import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.waste_enums import AssessmentSource, RiskLevel, SuggestedHandling


class ManualRiskAssessmentRequest(BaseModel):
    risk_level: RiskLevel
    suggested_handling: SuggestedHandling
    notes: str | None = Field(default=None, max_length=1000)


class WasteRiskAssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    waste_record_id: uuid.UUID
    risk_level: RiskLevel
    recyclability_decision: bool
    suggested_handling: SuggestedHandling
    source: AssessmentSource
    factors: dict
    explanation: str
    notes: str | None
    is_confirmed: bool
    confirmed_by: uuid.UUID | None
    confirmed_at: datetime | None
    created_at: datetime
