from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.analytics import AnalyticsResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsResponse)
def get_analytics_overview(
    period: str = Query("30d", pattern="^(7d|30d|90d|12m)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return AnalyticsService(db).build(current_user, period)
