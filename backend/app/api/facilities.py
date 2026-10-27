from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.facility import (
    AcceptedCategoriesUpdate,
    FacilityDashboardStats,
    FacilityProfileCreate,
    FacilityProfileResponse,
    FacilityProfileUpdate,
)
from app.schemas.waste import WasteCategoryResponse
from app.services.facility_service import (
    FacilityService,
    InvalidCategoryError,
    ProfileAlreadyExistsError,
    ProfileNotFoundError,
    ProfileAccessDeniedError,
)

router = APIRouter(prefix="/facilities", tags=["facilities"])

require_facility = require_roles(UserRole.FACILITY)


@router.get("/me", response_model=FacilityProfileResponse | None)
def get_my_profile(
    current_user: User = Depends(require_facility), db: Session = Depends(get_db)
):
    return FacilityService(db).get_profile(current_user.id)


@router.post(
    "/me", response_model=FacilityProfileResponse, status_code=status.HTTP_201_CREATED
)
def create_my_profile(
    payload: FacilityProfileCreate,
    current_user: User = Depends(require_facility),
    db: Session = Depends(get_db),
):
    try:
        return FacilityService(db).create_profile(user_id=current_user.id, data=payload)
    except ProfileAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A Waste Processing Facility profile already exists for this account. Use PUT to update it.",
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except InvalidCategoryError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more selected waste categories are invalid or inactive.")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.put("/me", response_model=FacilityProfileResponse)
def update_my_profile(
    payload: FacilityProfileUpdate,
    current_user: User = Depends(require_facility),
    db: Session = Depends(get_db),
):
    try:
        return FacilityService(db).update_profile(user_id=current_user.id, data=payload)
    except ProfileAccessDeniedError:
        raise HTTPException(status_code=403, detail="Only the organization owner or manager may edit this profile.")
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Waste Processing Facility profile exists yet. Create one first.",
        )
    except InvalidCategoryError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more selected waste categories are invalid or inactive.")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/me/accepted-categories", response_model=list[WasteCategoryResponse])
def get_accepted_categories(
    current_user: User = Depends(require_facility), db: Session = Depends(get_db)
):
    try:
        return FacilityService(db).get_accepted_categories(current_user.id)
    except ProfileAccessDeniedError:
        raise HTTPException(status_code=403, detail="Only the organization owner or manager may edit this profile.")
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Create a facility profile first."
        )


@router.put("/me/accepted-categories", response_model=list[WasteCategoryResponse])
def set_accepted_categories(
    payload: AcceptedCategoriesUpdate,
    current_user: User = Depends(require_facility),
    db: Session = Depends(get_db),
):
    try:
        return FacilityService(db).set_accepted_categories(
            user_id=current_user.id, category_ids=payload.category_ids
        )
    except ProfileAccessDeniedError:
        raise HTTPException(status_code=403, detail="Only the organization owner or manager may edit this profile.")
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Create a facility profile first."
        )
    except InvalidCategoryError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown waste category.")


@router.get("/me/stats", response_model=FacilityDashboardStats)
def get_my_dashboard_stats(
    current_user: User = Depends(require_facility), db: Session = Depends(get_db)
):
    return FacilityService(db).get_dashboard_stats(user=current_user)
