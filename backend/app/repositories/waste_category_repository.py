import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.waste_category import WasteCategory


class WasteCategoryRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_active(self) -> list[WasteCategory]:
        stmt = select(WasteCategory).where(WasteCategory.is_active.is_(True), WasteCategory.code != "PENDING").order_by(
            WasteCategory.name
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_by_id(self, category_id: uuid.UUID) -> WasteCategory | None:
        return self.db.get(WasteCategory, category_id)

    def get_by_code(self, code: str) -> WasteCategory | None:
        stmt = select(WasteCategory).where(WasteCategory.code == code)
        return self.db.execute(stmt).scalar_one_or_none()
