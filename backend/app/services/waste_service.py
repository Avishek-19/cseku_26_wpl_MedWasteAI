import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.hospital_profile import HospitalProfile
from app.models.waste_attachment import WasteAttachment
from app.models.waste_enums import WasteEventType, WasteStatus
from app.models.waste_record import WasteRecord
from app.repositories.hospital_repository import HospitalRepository
from app.services.organization_eligibility import can_profile_action
from app.repositories.waste_attachment_repository import WasteAttachmentRepository
from app.repositories.waste_category_repository import WasteCategoryRepository
from app.repositories.waste_record_repository import WasteRecordRepository
from app.rules.file_upload_rules import validate_upload
from app.schemas.waste import WasteRecordCreate
from app.services.waste_event_service import WasteEventService

settings = get_settings()


class HospitalProfileRequiredError(Exception):
    pass


class CategoryNotFoundError(Exception):
    pass


class WasteRecordNotFoundError(Exception):
    pass


class WasteService:
    def __init__(self, db: Session):
        self.db = db
        self.hospitals = HospitalRepository(db)
        self.categories = WasteCategoryRepository(db)
        self.records = WasteRecordRepository(db)
        self.attachments = WasteAttachmentRepository(db)
        self.events = WasteEventService(db)

    def _require_hospital_profile(self, user_id: uuid.UUID, *, action: str = "waste_read") -> HospitalProfile:
        profile = self.hospitals.get_by_user_id(user_id)
        if profile is None:
            raise HospitalProfileRequiredError()
        if not can_profile_action(self.db, profile, user_id, "HOSPITAL", action):
            raise PermissionError("Organization member cannot perform this waste operation")
        return profile

    def list_categories(self):
        return self.categories.list_active()

    def create_record(self, *, user_id: uuid.UUID, data: WasteRecordCreate) -> WasteRecord:
        profile = self._require_hospital_profile(user_id, action="waste_write")

       
        if data.category_id is not None:
            category = self.categories.get_by_id(data.category_id)
        else:
            category = self.categories.get_by_code("PENDING")

        if category is None or not category.is_active:
            raise CategoryNotFoundError()

        generated_at = data.generated_at or datetime.now(timezone.utc)
        sequence = self.records.next_sequence_value()
        waste_code = f"MW-{generated_at.year}-{sequence:06d}"

        record = WasteRecord(
            waste_code=waste_code,
            hospital_id=profile.id,
            category_id=category.id,
            reported_by=user_id,
            quantity=data.quantity,
            unit=data.unit,
            description=data.description,
            generated_at=generated_at,
            status=WasteStatus.REPORTED,
        )
        self.db.add(record)
        self.db.flush()
        self.events.record(
            waste_record_id=record.id,
            event_type=WasteEventType.REPORTED,
            status_snapshot=WasteStatus.REPORTED,
            actor_user_id=user_id,
            quantity=record.quantity,
            notes=f"Reported by {profile.name}.",
            metadata={"category": category.name, "unit": record.unit.value},
            commit=False,
        )
        # Reporting, first audit event and workflow task commit atomically.
        # This prevents the gap between the report API and the async worker.
        from app.models.business import EventOutbox
        self.db.add(EventOutbox(dedupe_key=f'waste-report:{record.id}',
            topic='waste.report.progress', payload={
                'record_id': str(record.id), 'user_id': str(user_id),
                'hospital_id': str(profile.id),
                'organization_id': str(profile.organization_id) if profile.organization_id else None,
            }))
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_record(self, *, user_id: uuid.UUID, record_id: uuid.UUID, action: str = "waste_read") -> WasteRecord:
        profile = self._require_hospital_profile(user_id, action=action)
        record = self.records.get_by_id_for_hospital(record_id=record_id, hospital_id=profile.id)
        if record is None:
            raise WasteRecordNotFoundError()
        return record

    def search_records(self, *, user_id: uuid.UUID, **filters):
        profile = self._require_hospital_profile(user_id)
        return self.records.search(hospital_id=profile.id, **filters)

    def add_attachment(
        self,
        *,
        user_id: uuid.UUID,
        record_id: uuid.UUID,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> WasteAttachment:
        self._require_hospital_profile(user_id, action="waste_write")
        record = self.get_record(user_id=user_id, record_id=record_id)
        validate_upload(content_type=content_type, size_bytes=len(content))

        safe_name = Path(filename.replace("\\", "/")).name.replace("\x00", "")[:180] or "attachment"
        #  # strip any directory components
        stored_name = f"{uuid.uuid4().hex}_{safe_name}"
        relative_path = f"waste/{record.id}/{stored_name}"

        storage_root = Path(settings.local_storage_dir)
        target_path = storage_root / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)

        attachment = WasteAttachment(
            waste_record_id=record.id,
            uploaded_by=user_id,
            original_filename=safe_name,
            storage_path=relative_path,
            content_type=content_type,
            size_bytes=len(content),
        )
        try:
            return self.attachments.create(attachment)
        except Exception:
            target_path.unlink(missing_ok=True)
            raise

    def get_attachment_for_download(
        self, *, user_id: uuid.UUID, record_id: uuid.UUID, attachment_id: uuid.UUID
    ) -> tuple[WasteAttachment, Path]:
        # Re-validates hospital ownership of the parent record before allowing download.
        self.get_record(user_id=user_id, record_id=record_id)
        attachment = self.attachments.get_by_id(attachment_id)
        if attachment is None or attachment.waste_record_id != record_id:
            raise WasteRecordNotFoundError()
        path = (Path(settings.local_storage_dir) / attachment.storage_path).resolve()
        if not path.is_relative_to(Path(settings.local_storage_dir).resolve()) or not path.is_file():
            raise WasteRecordNotFoundError()
        return attachment, path
