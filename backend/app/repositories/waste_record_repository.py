import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.waste_enums import WasteStatus
from app.models.waste_record import WasteRecord, waste_record_seq


class WasteRecordRepository:
    def __init__(self, db: Session):
        self.db = db

    def next_sequence_value(self) -> int:
        return self.db.execute(select(waste_record_seq.next_value())).scalar_one()

    def create(self, record: WasteRecord) -> WasteRecord:
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    
    def apply_classification(
        self, *, record: WasteRecord, category_id: uuid.UUID, status: WasteStatus, commit: bool = True
    ) -> WasteRecord:
        record.category_id = category_id
        record.status = status
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(record)
        return record
    
    def set_status(self, *, record: WasteRecord, status: WasteStatus, commit: bool = True) -> WasteRecord:
        record.status = status
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(record)
        return record

    def record_receipt(
        self, *, record: WasteRecord, received_quantity, received_by, status: WasteStatus, commit: bool = True
    ) -> WasteRecord:
        record.received_quantity = received_quantity
        record.received_by = received_by
        record.received_at = datetime.now(timezone.utc)
        record.status = status
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(record)
        return record

    def get_by_id(self, record_id: uuid.UUID) -> WasteRecord | None:
        return self.db.get(WasteRecord, record_id)

    def list_incoming_for_facility(self, facility_id: uuid.UUID) -> list[WasteRecord]:
        from app.models.matching_record import MatchingRecord

        stmt = (
            select(WasteRecord)
            .join(MatchingRecord, MatchingRecord.waste_record_id == WasteRecord.id)
            .options(selectinload(WasteRecord.attachments))
            .where(
                MatchingRecord.confirmed_facility_id == facility_id,
                MatchingRecord.is_confirmed.is_(True),
                WasteRecord.status.in_([
                    WasteStatus.IN_TRANSIT,
                    WasteStatus.DESTINATION_RECEIVED,
                    WasteStatus.PROCESSING,
                    WasteStatus.PROOF_SUBMITTED,
                    WasteStatus.VERIFIED,
                    WasteStatus.COMPLETED,
                ]),
            )
            .distinct()
        )
        return list(self.db.execute(stmt).scalars().all())


    def get_by_id_for_hospital(
        self, *, record_id: uuid.UUID, hospital_id: uuid.UUID
    ) -> WasteRecord | None:
        stmt = (
            select(WasteRecord)
            .options(selectinload(WasteRecord.attachments))
            .where(WasteRecord.id == record_id, WasteRecord.hospital_id == hospital_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def search(
        self,
        *,
        hospital_id: uuid.UUID,
        page: int,
        page_size: int,
        status: WasteStatus | None = None,
        category_id: uuid.UUID | None = None,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[WasteRecord], int]:
        conditions = [WasteRecord.hospital_id == hospital_id]

        if status is not None:
            conditions.append(WasteRecord.status == status)
        if category_id is not None:
            conditions.append(WasteRecord.category_id == category_id)
        if search:
            like = f"%{search.strip()}%"
            conditions.append(
                or_(WasteRecord.waste_code.ilike(like), WasteRecord.description.ilike(like))
            )
        if date_from is not None:
            conditions.append(WasteRecord.generated_at >= date_from)
        if date_to is not None:
            conditions.append(WasteRecord.generated_at <= date_to)

        count_stmt = select(func.count()).select_from(WasteRecord).where(*conditions)
        total = self.db.execute(count_stmt).scalar_one()

        items_stmt = (
            select(WasteRecord)
            .options(selectinload(WasteRecord.attachments))
            .where(*conditions)
            .order_by(WasteRecord.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(self.db.execute(items_stmt).scalars().all())
        return items, total

    def list_for_hospital(self, *, hospital_id: uuid.UUID, limit: int = 200) -> list[WasteRecord]:
        stmt = (
            select(WasteRecord)
            .options(selectinload(WasteRecord.category))
            .where(WasteRecord.hospital_id == hospital_id)
            .order_by(WasteRecord.generated_at.asc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())
