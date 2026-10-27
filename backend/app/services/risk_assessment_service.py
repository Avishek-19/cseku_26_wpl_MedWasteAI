from app.services.review_guard import lock_reviewable
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.waste_enums import AssessmentSource, WasteEventType, WasteStatus
from app.models.waste_risk_assessment import WasteRiskAssessment
from app.repositories.risk_rule_repository import RiskRuleRepository
from app.repositories.waste_record_repository import WasteRecordRepository
from app.repositories.waste_risk_assessment_repository import WasteRiskAssessmentRepository
from app.rules.risk_assessment_rules import assess_risk
from app.services.waste_event_service import WasteEventService
from app.services.waste_service import WasteService


class ClassificationRequiredError(Exception):
    pass


class NoRiskRuleConfiguredError(Exception):
    pass


class NoAssessmentYetError(Exception):
    pass


class AssessmentAlreadyConfirmedError(Exception):
    pass


class RiskAssessmentService:
    def __init__(self, db: Session):
        self.db = db
        self.waste_service = WasteService(db)
        self.risk_rules = RiskRuleRepository(db)
        self.assessments = WasteRiskAssessmentRepository(db)
        self.records = WasteRecordRepository(db)
        self.events = WasteEventService(db)

    def _require_classified(self, record):
        if record.status == WasteStatus.REPORTED:
            raise ClassificationRequiredError()

    def run_assessment(
        self, *, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> WasteRiskAssessment:
        record = self.waste_service.get_record(user_id=user_id, record_id=record_id, action="waste_write")
        record = lock_reviewable(self.db, record, risk=True)
        self._require_classified(record)

        rule = self.risk_rules.get_for_category(record.category_id)
        if rule is None:
            raise NoRiskRuleConfiguredError()

        result = assess_risk(
            rule=rule, category_is_recyclable=record.category.is_recyclable, quantity=record.quantity
        )

        entry = WasteRiskAssessment(
            waste_record_id=record.id,
            risk_level=result.risk_level,
            recyclability_decision=result.recyclability_decision,
            suggested_handling=result.suggested_handling,
            source=AssessmentSource.RULE_ENGINE,
            factors=result.factors,
            explanation=result.explanation,
            is_confirmed=False,
        )
        return self.assessments.create(entry)

    def list_history(
        self, *, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> list[WasteRiskAssessment]:
        self.waste_service.get_record(user_id=user_id, record_id=record_id)
        return self.assessments.list_for_record(record_id)

    def confirm_latest(
        self, *, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> WasteRiskAssessment:
        record = self.waste_service.get_record(user_id=user_id, record_id=record_id, action="waste_write")
        record = lock_reviewable(self.db, record, risk=True)
        latest = self.assessments.get_latest(record_id)
        if latest is None:
            raise NoAssessmentYetError()
        if latest.is_confirmed:
            raise AssessmentAlreadyConfirmedError()

        latest.is_confirmed = True
        latest.confirmed_by = user_id
        latest.confirmed_at = datetime.now(timezone.utc)

        self.records.set_status(record=record, status=WasteStatus.RISK_ASSESSED, commit=False)
        self.events.record(
            waste_record_id=record.id,
            event_type=WasteEventType.RISK_ASSESSED,
            status_snapshot=WasteStatus.RISK_ASSESSED,
            actor_user_id=user_id,
            quantity=record.quantity,
            notes=f"Confirmed as {latest.risk_level.value} risk, suggested handling: {latest.suggested_handling.value}.",
            metadata={"risk_level": latest.risk_level.value, "suggested_handling": latest.suggested_handling.value},
        )
        return latest

    def manual_override(
        self,
        *,
        user_id: uuid.UUID,
        record_id: uuid.UUID,
        risk_level,
        suggested_handling,
        notes: str | None,
    ) -> WasteRiskAssessment:
        record = self.waste_service.get_record(user_id=user_id, record_id=record_id, action="waste_write")
        record = lock_reviewable(self.db, record, risk=True)
        self._require_classified(record)

        entry = WasteRiskAssessment(
            waste_record_id=record.id,
            risk_level=risk_level,
            # A human directly set the handling, so recyclability follows their call.
            recyclability_decision=suggested_handling.value == "recycle",
            suggested_handling=suggested_handling,
            source=AssessmentSource.MANUAL,
            factors={},
            explanation="Manually assessed by hospital staff, overriding any system suggestion.",
            notes=notes,
            is_confirmed=True,
            confirmed_by=user_id,
            confirmed_at=datetime.now(timezone.utc),
        )
        entry = self.assessments.create(entry, commit=False)

        self.records.set_status(record=record, status=WasteStatus.RISK_ASSESSED, commit=False)
        self.events.record(
            waste_record_id=record.id,
            event_type=WasteEventType.RISK_ASSESSED,
            status_snapshot=WasteStatus.RISK_ASSESSED,
            actor_user_id=user_id,
            quantity=record.quantity,
            notes=(
                f"Manually assessed as {entry.risk_level.value} risk, handling: "
                f"{entry.suggested_handling.value}."
            )
            + (f" {notes}" if notes else ""),
            metadata={"risk_level": entry.risk_level.value, "suggested_handling": entry.suggested_handling.value},
        )
        return entry
