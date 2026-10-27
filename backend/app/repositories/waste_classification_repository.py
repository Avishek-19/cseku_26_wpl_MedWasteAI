import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.waste_classification import WasteClassification


class WasteClassificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, classification: WasteClassification, *, commit: bool = True) -> WasteClassification:
        self.db.add(classification)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(classification)
        return classification

    def list_for_record(self, waste_record_id: uuid.UUID) -> list[WasteClassification]:
        stmt = (
            select(WasteClassification)
            .where(WasteClassification.waste_record_id == waste_record_id)
            .order_by(WasteClassification.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_latest(self, waste_record_id: uuid.UUID) -> WasteClassification | None:
        stmt = (
            select(WasteClassification)
            .where(WasteClassification.waste_record_id == waste_record_id)
            .order_by(WasteClassification.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()
