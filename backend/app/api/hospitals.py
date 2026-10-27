from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.hospital import (
    HospitalDashboardStats,
    HospitalProfileCreate,
    HospitalProfileResponse,
    HospitalProfileUpdate,
)
from app.services.hospital_service import (
    HospitalService,
    ProfileAlreadyExistsError,
    ProfileNotFoundError,
    ProfileAccessDeniedError,
)

router = APIRouter(prefix="/hospitals", tags=["hospitals"])

require_hospital = require_roles(UserRole.HOSPITAL)


@router.get("/me", response_model=HospitalProfileResponse | None)
def get_my_profile(
    current_user: User = Depends(require_hospital), db: Session = Depends(get_db)
):
    return HospitalService(db).get_profile(current_user.id)


@router.post(
    "/me", response_model=HospitalProfileResponse, status_code=status.HTTP_201_CREATED
)
def create_my_profile(
    payload: HospitalProfileCreate,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return HospitalService(db).create_profile(user_id=current_user.id, data=payload)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=403 if isinstance(exc, PermissionError) else 422, detail=str(exc))
    except ProfileAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A hospital profile already exists for this account. Use PUT to update it.",
        )


@router.put("/me", response_model=HospitalProfileResponse)
def update_my_profile(
    payload: HospitalProfileUpdate,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        return HospitalService(db).update_profile(user_id=current_user.id, data=payload)
    except ProfileAccessDeniedError:
        raise HTTPException(status_code=403, detail="Only the organization owner or manager may edit this profile.")
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hospital profile exists yet. Create one first with POST /hospitals/me.",
        )


@router.get("/me/stats", response_model=HospitalDashboardStats)
def get_my_dashboard_stats(
    current_user: User = Depends(require_hospital), db: Session = Depends(get_db)
):
    return HospitalService(db).get_dashboard_stats(user=current_user)
