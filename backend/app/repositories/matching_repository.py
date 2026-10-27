import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.matching_record import MatchingRecord


class MatchingRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, record: MatchingRecord) -> MatchingRecord:
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def list_for_record(self, waste_record_id: uuid.UUID) -> list[MatchingRecord]:
        stmt = (
            select(MatchingRecord)
            .where(MatchingRecord.waste_record_id == waste_record_id)
            .order_by(MatchingRecord.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_latest(self, waste_record_id: uuid.UUID) -> MatchingRecord | None:
        stmt = (
            select(MatchingRecord)
            .where(MatchingRecord.waste_record_id == waste_record_id)
            .order_by(MatchingRecord.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_confirmed_for_record(self, waste_record_id: uuid.UUID) -> MatchingRecord | None:
        stmt = select(MatchingRecord).where(
            MatchingRecord.waste_record_id == waste_record_id,
            MatchingRecord.is_confirmed.is_(True),
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def save(self, record: MatchingRecord, *, commit: bool = True) -> MatchingRecord:
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(record)
        return record
