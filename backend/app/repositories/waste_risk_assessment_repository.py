import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.waste_risk_assessment import WasteRiskAssessment


class WasteRiskAssessmentRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, assessment: WasteRiskAssessment, *, commit: bool = True) -> WasteRiskAssessment:
        self.db.add(assessment)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(assessment)
        return assessment

    def list_for_record(self, waste_record_id: uuid.UUID) -> list[WasteRiskAssessment]:
        stmt = (
            select(WasteRiskAssessment)
            .where(WasteRiskAssessment.waste_record_id == waste_record_id)
            .order_by(WasteRiskAssessment.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_latest(self, waste_record_id: uuid.UUID) -> WasteRiskAssessment | None:
        stmt = (
            select(WasteRiskAssessment)
            .where(WasteRiskAssessment.waste_record_id == waste_record_id)
            .order_by(WasteRiskAssessment.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_latest_confirmed(self, waste_record_id: uuid.UUID) -> WasteRiskAssessment | None:
        stmt = (
            select(WasteRiskAssessment)
            .where(
                WasteRiskAssessment.waste_record_id == waste_record_id,
                WasteRiskAssessment.is_confirmed.is_(True),
            )
            .order_by(WasteRiskAssessment.confirmed_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()
