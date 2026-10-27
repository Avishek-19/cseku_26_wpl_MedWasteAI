import uuid

from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.repositories.notification_repository import NotificationRepository
from app.schemas.notification import NotificationListResponse, NotificationResponse


class NotificationService:
    def __init__(self, db: Session):
        self.db = db
        self.notifications = NotificationRepository(db)

    def notify(
        self,
        *,
        user_id: uuid.UUID,
        title: str,
        body: str,
        waste_record_id: uuid.UUID | None = None,
    ) -> Notification:
        notification = Notification(
            user_id=user_id, title=title, body=body, waste_record_id=waste_record_id
        )
        return self.notifications.create(notification)

    def list_for_user(self, user_id: uuid.UUID) -> NotificationListResponse:
        items = self.notifications.list_for_user(user_id)
        unread = self.notifications.unread_count(user_id)
        return NotificationListResponse(
            items=[NotificationResponse.model_validate(n) for n in items], unread_count=unread
        )

    def mark_read(self, *, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification | None:
        return self.notifications.mark_read(user_id=user_id, notification_id=notification_id)

    def mark_all_read(self, user_id: uuid.UUID) -> None:
        self.notifications.mark_all_read(user_id)
