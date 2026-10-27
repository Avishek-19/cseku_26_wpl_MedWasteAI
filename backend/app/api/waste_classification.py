from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.classification import (
    ManualClassificationRequest,
    WasteClassificationResponse,
)
from app.services.waste_classification_service import (
    CategoryNotFoundError,
    PendingClassificationError,
    ClassificationAlreadyConfirmedError,
    NoClassificationYetError,
    WasteClassificationService,
)
from app.services.waste_service import HospitalProfileRequiredError, WasteRecordNotFoundError

router = APIRouter(prefix="/waste/{record_id}/classifications", tags=["classification"])

require_hospital = require_roles(UserRole.HOSPITAL)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waste record not found.")


def _profile_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_412_PRECONDITION_FAILED,
        detail="Complete your hospital profile first.",
    )


@router.post("/run", response_model=WasteClassificationResponse, status_code=status.HTTP_201_CREATED)
def run_classification(
    record_id: UUID,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return WasteClassificationService(db).run_classification(
            user_id=current_user.id, record_id=record_id
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except HospitalProfileRequiredError:
        raise _profile_required()
    except WasteRecordNotFoundError:
        raise _not_found()
    except CategoryNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Classification rule referenced an unknown category.",
        )


@router.get("", response_model=list[WasteClassificationResponse])
def list_classification_history(
    record_id: UUID,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return WasteClassificationService(db).list_history(
            user_id=current_user.id, record_id=record_id
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except HospitalProfileRequiredError:
        raise _profile_required()
    except WasteRecordNotFoundError:
        raise _not_found()


@router.post("/confirm", response_model=WasteClassificationResponse)
def confirm_classification(
    record_id: UUID,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return WasteClassificationService(db).confirm_latest(
            user_id=current_user.id, record_id=record_id
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except HospitalProfileRequiredError:
        raise _profile_required()
    except WasteRecordNotFoundError:
        raise _not_found()
    except PendingClassificationError:
        raise HTTPException(409, "Select a real handling category using manual classification before confirming this batch.")
    except NoClassificationYetError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run classification before confirming a result.",
        )
    except ClassificationAlreadyConfirmedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This classification has already been confirmed.",
        )


@router.post("/override", response_model=WasteClassificationResponse)
def override_classification(
    record_id: UUID,
    payload: ManualClassificationRequest,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return WasteClassificationService(db).manual_override(
            user_id=current_user.id,
            record_id=record_id,
            category_id=payload.category_id,
            notes=payload.notes,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except HospitalProfileRequiredError:
        raise _profile_required()
    except WasteRecordNotFoundError:
        raise _not_found()
    except CategoryNotFoundError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown waste category.")
