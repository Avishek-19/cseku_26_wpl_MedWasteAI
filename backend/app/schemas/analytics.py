from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class AnalyticsSummary(BaseModel):
    total_batches: int = 0
    tracked_weight_kg: Decimal = Decimal("0")
    recyclable_weight_kg: Decimal = Decimal("0")
    recycled_weight_kg: Decimal = Decimal("0")
    treated_weight_kg: Decimal = Decimal("0")
    disposed_weight_kg: Decimal = Decimal("0")
    recycling_rate: float = Field(default=0, ge=0, le=100)
    high_risk_batches: int = 0
    active_batches: int = 0
    completed_batches: int = 0


class AnalyticsPoint(BaseModel):
    label: str
    value: float = 0


class AnalyticsCategory(BaseModel):
    name: str
    batches: int
    weight_kg: float
    percentage: float


class AnalyticsResponse(BaseModel):
    scope: str
    period: str
    from_date: datetime
    to_date: datetime
    summary: AnalyticsSummary
    waste_trend: list[AnalyticsPoint]
    category_distribution: list[AnalyticsCategory]
    processing: list[AnalyticsPoint]
    notes: list[str]
    generated_at: datetime
