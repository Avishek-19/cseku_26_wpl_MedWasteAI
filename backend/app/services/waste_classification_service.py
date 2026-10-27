from app.services.review_guard import lock_reviewable
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.waste_classification import WasteClassification
from app.models.waste_enums import (
    ClassificationConfidence,
    ClassificationSource,
    WasteEventType,
    WasteStatus,
)
from app.repositories.waste_category_repository import WasteCategoryRepository
from app.repositories.waste_classification_repository import WasteClassificationRepository
from app.repositories.waste_record_repository import WasteRecordRepository
from app.rules.classification_rules import classify
from app.services.waste_event_service import WasteEventService
from app.services.waste_service import WasteService


class NoClassificationYetError(Exception):
    pass


class ClassificationAlreadyConfirmedError(Exception):
    pass


class PendingClassificationError(Exception):
    pass


class CategoryNotFoundError(Exception):
    pass


class WasteClassificationService:
    def __init__(self, db: Session):
        self.db = db
        self.waste_service = WasteService(db)
        self.categories = WasteCategoryRepository(db)
        self.classifications = WasteClassificationRepository(db)
        self.records = WasteRecordRepository(db)
        self.events = WasteEventService(db)

    def run_classification(
        self, *, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> WasteClassification:
        record = self.waste_service.get_record(user_id=user_id, record_id=record_id, action="waste_write")
        record = lock_reviewable(self.db, record)
        result = classify(
            description=record.description, reported_category_code=record.category.code
        )
        suggested_category = self.categories.get_by_code(result.suggested_category_code)
        if suggested_category is None:
            # Shouldn't happen with seeded data, but fail loudly rather than
            # silently classifying against a nonexistent category.
            raise CategoryNotFoundError()

        entry = WasteClassification(
            waste_record_id=record.id,
            suggested_category_id=suggested_category.id,
            source=ClassificationSource.RULE_ENGINE,
            confidence=ClassificationConfidence(result.confidence),
            matched_rules=[asdict(m) for m in result.matched_rules],
            explanation=result.explanation,
            is_confirmed=False,
        )
        return self.classifications.create(entry)

    def list_history(self, *, user_id: uuid.UUID, record_id: uuid.UUID) -> list[WasteClassification]:
        self.waste_service.get_record(user_id=user_id, record_id=record_id)  # ownership check
        return self.classifications.list_for_record(record_id)

    def confirm_latest(
        self, *, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> WasteClassification:
        record = self.waste_service.get_record(user_id=user_id, record_id=record_id, action="waste_write")
        record = lock_reviewable(self.db, record)
        latest = self.classifications.get_latest(record_id)
        if latest is None:
            raise NoClassificationYetError()
        if latest.is_confirmed:
            raise ClassificationAlreadyConfirmedError()

        if record.category.code == "PENDING" and latest.suggested_category_id == record.category_id:
            raise PendingClassificationError()
        latest.is_confirmed = True
        latest.confirmed_by = user_id
        latest.confirmed_at = datetime.now(timezone.utc)

        from sqlalchemy import update
        from app.models.waste_risk_assessment import WasteRiskAssessment
        self.db.execute(update(WasteRiskAssessment).where(
            WasteRiskAssessment.waste_record_id == record_id).values(is_confirmed=False))
        self.records.apply_classification(
            record=record, category_id=latest.suggested_category_id, status=WasteStatus.CLASSIFIED, commit=False
        )
        self.events.record(
            waste_record_id=record.id,
            event_type=WasteEventType.CLASSIFIED,
            status_snapshot=WasteStatus.CLASSIFIED,
            actor_user_id=user_id,
            quantity=record.quantity,
            notes=f"Confirmed as {latest.suggested_category.name} ({latest.confidence.value} confidence).",
            metadata={"category": latest.suggested_category.name, "source": latest.source.value},
        )
        return latest

    def manual_override(
        self,
        *,
        user_id: uuid.UUID,
        record_id: uuid.UUID,
        category_id: uuid.UUID,
        notes: str | None,
    ) -> WasteClassification:
        record = self.waste_service.get_record(user_id=user_id, record_id=record_id, action="waste_write")
        record = lock_reviewable(self.db, record)
        category = self.categories.get_by_id(category_id)
        if category is None or not category.is_active or category.code == "PENDING":
            raise CategoryNotFoundError()

        entry = WasteClassification(
            waste_record_id=record.id,
            suggested_category_id=category.id,
            source=ClassificationSource.MANUAL,
            confidence=ClassificationConfidence.HIGH,  # a human made an explicit choice
            matched_rules=[],
            explanation="Manually classified by hospital staff, overriding any system suggestion.",
            notes=notes,
            is_confirmed=True,
            confirmed_by=user_id,
            confirmed_at=datetime.now(timezone.utc),
        )
        entry = self.classifications.create(entry, commit=False)

        from sqlalchemy import update
        from app.models.waste_risk_assessment import WasteRiskAssessment
        self.db.execute(update(WasteRiskAssessment).where(
            WasteRiskAssessment.waste_record_id == record_id).values(is_confirmed=False))
        self.records.apply_classification(
            record=record, category_id=category.id, status=WasteStatus.CLASSIFIED, commit=False
        )
        self.events.record(
            waste_record_id=record.id,
            event_type=WasteEventType.CLASSIFIED,
            status_snapshot=WasteStatus.CLASSIFIED,
            actor_user_id=user_id,
            quantity=record.quantity,
            notes=f"Manually classified as {category.name}." + (f" {notes}" if notes else ""),
            metadata={"category": category.name, "source": "manual"},
        )
        return entry
