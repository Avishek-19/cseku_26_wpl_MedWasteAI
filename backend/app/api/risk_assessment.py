from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.risk_assessment import (
    ManualRiskAssessmentRequest,
    WasteRiskAssessmentResponse,
)
from app.services.risk_assessment_service import (
    AssessmentAlreadyConfirmedError,
    ClassificationRequiredError,
    NoAssessmentYetError,
    NoRiskRuleConfiguredError,
    RiskAssessmentService,
)
from app.services.waste_service import HospitalProfileRequiredError, WasteRecordNotFoundError

router = APIRouter(prefix="/waste/{record_id}/risk-assessments", tags=["risk-assessment"])

require_hospital = require_roles(UserRole.HOSPITAL)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waste record not found.")


def _profile_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_412_PRECONDITION_FAILED,
        detail="Complete your hospital profile first.",
    )


def _classification_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Classify this waste record before running a risk assessment.",
    )


@router.post("/run", response_model=WasteRiskAssessmentResponse, status_code=status.HTTP_201_CREATED)
def run_risk_assessment(
    record_id: UUID,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return RiskAssessmentService(db).run_assessment(
            user_id=current_user.id, record_id=record_id
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except HospitalProfileRequiredError:
        raise _profile_required()
    except WasteRecordNotFoundError:
        raise _not_found()
    except ClassificationRequiredError:
        raise _classification_required()
    except NoRiskRuleConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No risk rule is configured for this waste category.",
        )


@router.get("", response_model=list[WasteRiskAssessmentResponse])
def list_risk_assessment_history(
    record_id: UUID,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return RiskAssessmentService(db).list_history(
            user_id=current_user.id, record_id=record_id
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except HospitalProfileRequiredError:
        raise _profile_required()
    except WasteRecordNotFoundError:
        raise _not_found()


@router.post("/confirm", response_model=WasteRiskAssessmentResponse)
def confirm_risk_assessment(
    record_id: UUID,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return RiskAssessmentService(db).confirm_latest(
            user_id=current_user.id, record_id=record_id
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except HospitalProfileRequiredError:
        raise _profile_required()
    except WasteRecordNotFoundError:
        raise _not_found()
    except NoAssessmentYetError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run a risk assessment before confirming a result.",
        )
    except AssessmentAlreadyConfirmedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This risk assessment has already been confirmed.",
        )


@router.post("/override", response_model=WasteRiskAssessmentResponse)
def override_risk_assessment(
    record_id: UUID,
    payload: ManualRiskAssessmentRequest,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return RiskAssessmentService(db).manual_override(
            user_id=current_user.id,
            record_id=record_id,
            risk_level=payload.risk_level,
            suggested_handling=payload.suggested_handling,
            notes=payload.notes,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except HospitalProfileRequiredError:
        raise _profile_required()
    except WasteRecordNotFoundError:
        raise _not_found()
    except ClassificationRequiredError:
        raise _classification_required()
