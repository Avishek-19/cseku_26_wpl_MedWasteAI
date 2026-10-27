import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.processing_record import ProcessingRecord

class ProcessingRepository:
    def __init__(self, db: Session): self.db = db
    def get_for_waste(self, waste_record_id: uuid.UUID):
        return self.db.execute(select(ProcessingRecord).where(ProcessingRecord.waste_record_id == waste_record_id)).scalar_one_or_none()
    def list_for_facility(self, facility_id: uuid.UUID):
        stmt = select(ProcessingRecord).where(ProcessingRecord.facility_id == facility_id).order_by(ProcessingRecord.created_at.desc())
        return list(self.db.execute(stmt).scalars().all())
    def create(self, record):
        self.db.add(record); self.db.commit(); self.db.refresh(record); return record
    def save(self, record):
        self.db.commit(); self.db.refresh(record); return record
