from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.matching import MatchConfirmRequest, MatchingRecordResponse
from app.services.matching_service import (
    InvalidDestinationError,
    MatchAlreadyConfirmedError,
    MatchingService,
    NoMatchingRunYetError,
    RiskAssessmentRequiredError,
)
from app.services.waste_service import HospitalProfileRequiredError, WasteRecordNotFoundError

router = APIRouter(prefix="/waste/{record_id}/matching", tags=["matching"])

require_hospital = require_roles(UserRole.HOSPITAL)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waste record not found.")


def _profile_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_412_PRECONDITION_FAILED,
        detail="Complete your hospital profile first.",
    )


@router.post("/run", response_model=MatchingRecordResponse, status_code=status.HTTP_201_CREATED)
def run_matching(
    record_id: UUID,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return MatchingService(db).run_matching(user_id=current_user.id, record_id=record_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except HospitalProfileRequiredError:
        raise _profile_required()
    except WasteRecordNotFoundError:
        raise _not_found()
    except RiskAssessmentRequiredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Confirm a risk assessment before matching a destination.",
        )


@router.get("", response_model=list[MatchingRecordResponse])
def list_matching_history(
    record_id: UUID,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return MatchingService(db).list_history(user_id=current_user.id, record_id=record_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except HospitalProfileRequiredError:
        raise _profile_required()
    except WasteRecordNotFoundError:
        raise _not_found()


@router.post("/confirm", response_model=MatchingRecordResponse)
def confirm_match(
    record_id: UUID,
    payload: MatchConfirmRequest,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return MatchingService(db).confirm_match(
            user_id=current_user.id, record_id=record_id, destination_id=payload.destination_id
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except HospitalProfileRequiredError:
        raise _profile_required()
    except WasteRecordNotFoundError:
        raise _not_found()
    except NoMatchingRunYetError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run matching before confirming a destination.",
        )
    except MatchAlreadyConfirmedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This match has already been confirmed."
        )
    except InvalidDestinationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That destination wasn't among the ranked candidates.",
        )
