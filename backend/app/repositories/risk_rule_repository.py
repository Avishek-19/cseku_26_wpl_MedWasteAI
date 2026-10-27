import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.risk_rule import RiskRule


class RiskRuleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_for_category(self, category_id: uuid.UUID) -> RiskRule | None:
        stmt = select(RiskRule).where(
            RiskRule.category_id == category_id, RiskRule.is_active.is_(True)
        )
        return self.db.execute(stmt).scalar_one_or_none()
