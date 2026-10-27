import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.waste_attachment import WasteAttachment


class WasteAttachmentRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, attachment: WasteAttachment) -> WasteAttachment:
        self.db.add(attachment)
        self.db.commit()
        self.db.refresh(attachment)
        return attachment

    def get_by_id(self, attachment_id: uuid.UUID) -> WasteAttachment | None:
        return self.db.get(WasteAttachment, attachment_id)
