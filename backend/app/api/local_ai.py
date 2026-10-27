from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.ai import AIAnalysisResponse
from app.services.local_ai_service import LocalAIService
from app.services.waste_service import HospitalProfileRequiredError, WasteRecordNotFoundError

router = APIRouter(prefix="/waste/{record_id}/ai", tags=["local-ai"])
require_hospital = require_roles(UserRole.HOSPITAL)


@router.post("/analyze", response_model=AIAnalysisResponse)
def analyze_waste(
    record_id: UUID,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return LocalAIService(db).analyze(user_id=current_user.id, record_id=record_id)
    except HospitalProfileRequiredError:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Complete your hospital profile first.",
        )
    except WasteRecordNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waste record not found.")
