from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.waste_event import WasteEventResponse
from app.services.waste_event_service import WasteEventService
from app.services.waste_service import HospitalProfileRequiredError, WasteRecordNotFoundError, WasteService

router = APIRouter(prefix="/waste/{record_id}/timeline", tags=["timeline"])

require_hospital = require_roles(UserRole.HOSPITAL)


@router.get("", response_model=list[WasteEventResponse])
def get_timeline(
    record_id: UUID,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        # Ownership check — reuses the same rule every other waste sub-resource follows.
        WasteService(db).get_record(user_id=current_user.id, record_id=record_id)
    except HospitalProfileRequiredError:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Complete your hospital profile first.",
        )
    except WasteRecordNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waste record not found.")

    return WasteEventService(db).list_timeline(record_id)
