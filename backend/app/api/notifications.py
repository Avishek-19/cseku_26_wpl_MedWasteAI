from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.notification import NotificationListResponse, NotificationResponse
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return NotificationService(db).list_for_user(current_user.id)


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def mark_read(
    notification_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = NotificationService(db).mark_read(
        user_id=current_user.id, notification_id=notification_id
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found.")
    return notification


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    NotificationService(db).mark_all_read(current_user.id)
