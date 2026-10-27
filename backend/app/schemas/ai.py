import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AIClassificationSuggestion(BaseModel):
    category_code: str
    category_name: str
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    requires_verification: bool = True


class AIRiskSuggestion(BaseModel):
    risk_level: str
    suggested_handling: str
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    requires_verification: bool = True


class AIRecyclabilitySuggestion(BaseModel):
    recyclable: bool
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    requires_verification: bool = True



class AIProcessingSuggestion(BaseModel):
    required_processing: str
    acceptable_methods: list[str]
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    requires_verification: bool = True

class AIImageAnalysis(BaseModel):
    status: str
    model: str | None = None
    observations: str
    suggested_category: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    requires_verification: bool = True


class AIAnomalyAnalysis(BaseModel):
    status: str
    is_anomaly: bool
    score: float
    baseline_mean: float | None = None
    baseline_median: float | None = None
    message: str
    requires_verification: bool = True


class AITrendPoint(BaseModel):
    period: str
    quantity: float


class AITrendPrediction(BaseModel):
    status: str
    method: str
    direction: str
    next_period_quantity: float | None = None
    points: list[AITrendPoint]
    message: str
    is_estimate: bool = True


class AIMatchingAssistance(BaseModel):
    status: str
    recommendation: str | None = None
    candidates: list[dict[str, Any]] = []
    explanation: str
    requires_verification: bool = True


class AIAnalysisResponse(BaseModel):
    waste_record_id: uuid.UUID
    generated_at: datetime
    provider: str
    model: str | None
    disclaimer: str
    summary: str
    classification: AIClassificationSuggestion
    risk: AIRiskSuggestion
    recyclability: AIRecyclabilitySuggestion
    processing: AIProcessingSuggestion
    image: AIImageAnalysis
    anomaly: AIAnomalyAnalysis
    trend: AITrendPrediction
    matching: AIMatchingAssistance
