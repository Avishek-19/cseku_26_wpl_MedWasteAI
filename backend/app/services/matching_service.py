from app.services.review_guard import lock_reviewable
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.matching_record import MatchingRecord
from app.models.user import User
from app.models.facility_profile import TreatmentFacilityProfile
from app.services.organization_eligibility import eligible_facility
from app.models.waste_enums import DestinationType, RiskLevel, SuggestedHandling, WasteEventType
from app.repositories.facility_repository import FacilityRepository
from app.repositories.hospital_repository import HospitalRepository
from app.repositories.matching_repository import MatchingRepository
from app.repositories.waste_risk_assessment_repository import WasteRiskAssessmentRepository
from app.rules.matching_rules import filter_by_capacity, rank_candidates
from app.rules.processing_rules import required_processing
from app.services.waste_event_service import WasteEventService
from app.services.waste_service import WasteService
from app.services.quantity_service import quantity_to_kg


class RiskAssessmentRequiredError(Exception): pass
class NoMatchingRunYetError(Exception): pass
class MatchAlreadyConfirmedError(Exception): pass
class InvalidDestinationError(Exception): pass


class MatchingService:
    def __init__(self, db: Session):
        self.db = db
        self.waste_service = WasteService(db)
        self.matches = MatchingRepository(db)
        self.facilities = FacilityRepository(db)
        self.risk_assessments = WasteRiskAssessmentRepository(db)
        self.hospitals = HospitalRepository(db)
        self.events = WasteEventService(db)

    def run_matching(self, *, user_id: uuid.UUID, record_id: uuid.UUID) -> MatchingRecord:
        record = self.waste_service.get_record(user_id=user_id, record_id=record_id, action="pickup_write")
        record = lock_reviewable(self.db, record, matching=True)
        assessment = self.risk_assessments.get_latest_confirmed(record_id)
        if assessment is None:
            raise RiskAssessmentRequiredError()

        hospital = self.hospitals.get_by_id(record.hospital_id)
        high_risk = assessment.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        quantity = quantity_to_kg(record.quantity, record.unit)
        if quantity is None:
            entry = MatchingRecord(
                waste_record_id=record.id,
                destination_type=DestinationType.WASTE_PROCESSING_FACILITY,
                candidates=[],
                explanation="The platform cannot safely compare this batch's unit with kg-based facility capacity because no scientifically valid conversion is configured. Status: REQUIRES_MANUAL_REVIEW.",
                processing_method=None,
                routing_status="requires_manual_review",
                routing_reason="Facility capacity is stored in kg and this batch unit cannot be safely converted to kg.",
                decision_method="deterministic_matching",
                match_score=None,
                requires_human_verification=True,
            )
            return self.matches.create(entry)
        processing_method, acceptable_methods = required_processing(
            category_code=record.category.code,
            risk_level=assessment.risk_level,
            handling=assessment.suggested_handling,
        )

        raw_candidates = self.facilities.list_accepting_category(record.category_id)
        # Unified destination: only verified, available processing facilities are candidates.
        candidates = [
            f for f in raw_candidates
            if eligible_facility(self.db, f, new_work=True)
            and any(str(s).upper() in acceptable_methods for s in (f.processing_services or []))
        ]
        eligible = filter_by_capacity(candidates=candidates, quantity=quantity)
        ranked = rank_candidates(
            candidates=eligible,
            quantity=quantity,
            hospital_city=hospital.city if hospital else "",
            hospital_region=hospital.region if hospital else "",
            high_risk=high_risk,
            required_processing=processing_method,
        )

        candidates_json = []
        for sc in ranked:
            services = [str(s).upper() for s in (sc.candidate.processing_services or [])]
            method = processing_method if processing_method in services else next(
                (m for m in acceptable_methods if m in services), processing_method
            )
            candidates_json.append({
                "id": str(sc.candidate.id),
                "name": sc.candidate.name,
                "city": sc.candidate.city,
                "score": sc.score,
                "is_verified": sc.candidate.is_verified,
                "reasons": sc.reasons + [f"Processing: {method}"],
                "processing_method": method,
            })

        if not candidates_json:
            explanation = (
                "No suitable verified Waste Processing Facility was found for the required "
                f"processing ({processing_method}) with compatible waste handling and available capacity. "
                "Status: REQUIRES_MANUAL_REVIEW."
            )
            routing_status = "requires_manual_review"
            score = None
            reason = "No verified facility with the required processing capability and available capacity was found."
        else:
            top = candidates_json[0]
            explanation = (
                f"Selected from {len(candidates_json)} eligible Waste Processing Facility candidate(s). "
                f"Recommended {top['name']} for {top['processing_method']} (score {top['score']}/100)."
            )
            routing_status = "recommended"
            score = top["score"]
            processing_method = top["processing_method"]
            reason = "Selected using safety compatibility, processing capability, verification, capacity, availability, location, and priority."

        entry = MatchingRecord(
            waste_record_id=record.id,
            destination_type=DestinationType.WASTE_PROCESSING_FACILITY,
            candidates=candidates_json,
            explanation=explanation,
            processing_method=processing_method,
            routing_status=routing_status,
            routing_reason=reason,
            decision_method="deterministic_matching",
            match_score=score,
            requires_human_verification=True,
        )
        return self.matches.create(entry)

    def list_history(self, *, user_id: uuid.UUID, record_id: uuid.UUID) -> list[MatchingRecord]:
        self.waste_service.get_record(user_id=user_id, record_id=record_id)
        return self.matches.list_for_record(record_id)

    def confirm_match(self, *, user_id: uuid.UUID, record_id: uuid.UUID, destination_id: uuid.UUID | None) -> MatchingRecord:
        record = self.waste_service.get_record(user_id=user_id, record_id=record_id, action="pickup_write")
        record = lock_reviewable(self.db, record, matching=True)
        latest = self.matches.get_latest(record_id)
        if latest is None or not latest.candidates:
            raise NoMatchingRunYetError()
        if latest.is_confirmed:
            raise MatchAlreadyConfirmedError()

        chosen_id = str(destination_id) if destination_id else latest.candidates[0]["id"]
        chosen = next((c for c in latest.candidates if c["id"] == chosen_id), None)
        if chosen is None:
            raise InvalidDestinationError()

        # Lock both record and destination: two matching requests cannot
        # race the same batch or overcommit facility capacity.
        from sqlalchemy import select
        from app.models.waste_record import WasteRecord
        locked_record = self.db.scalar(select(WasteRecord).where(
            WasteRecord.id == record_id).with_for_update(of=WasteRecord))
        if locked_record is None:
            raise InvalidDestinationError()
        if self.db.scalar(select(MatchingRecord.id).where(
            MatchingRecord.waste_record_id == record_id,
            MatchingRecord.is_confirmed.is_(True)).limit(1)):
            raise MatchAlreadyConfirmedError()
        facility = self.db.scalar(select(TreatmentFacilityProfile).where(
            TreatmentFacilityProfile.id == uuid.UUID(chosen_id)).with_for_update(of=TreatmentFacilityProfile))
        facility_user = self.db.get(User, facility.user_id) if facility else None
        if facility is None or facility_user is None or not facility_user.is_active or not eligible_facility(self.db, facility,
                need_capability=chosen.get('processing_method', latest.processing_method), new_work=True):
            raise InvalidDestinationError()
        quantity_kg = quantity_to_kg(record.quantity, record.unit)
        if quantity_kg is None or Decimal(str(facility.capacity_kg)) - Decimal(str(facility.current_utilization_kg)) < quantity_kg:
            raise InvalidDestinationError()

        # Re-check rules against live data; historic recommendations may be stale.
        from app.rules.processing_rules import required_processing
        assessment = self.risk_assessments.get_latest_confirmed(record_id)
        if assessment is None:
            raise InvalidDestinationError()
        _, allowed = required_processing(category_code=record.category.code,
            risk_level=assessment.risk_level, handling=assessment.suggested_handling)
        if chosen.get('processing_method', latest.processing_method) not in allowed:
            raise InvalidDestinationError()
        latest.confirmed_facility_id = uuid.UUID(chosen_id)
        latest.is_confirmed = True
        latest.confirmed_by = user_id
        latest.confirmed_at = datetime.now(timezone.utc)
        latest.routing_status = "assigned"
        if facility is not None:
            facility.current_utilization_kg = Decimal(str(facility.current_utilization_kg)) + quantity_kg
        saved = self.matches.save(latest, commit=False)

        self.events.record(
            waste_record_id=record.id,
            event_type=WasteEventType.MATCHED,
            status_snapshot=record.status,
            actor_user_id=user_id,
            quantity=record.quantity,
            notes=f"Matched to {chosen['name']} (Waste Processing Facility), {chosen.get('processing_method', latest.processing_method)}; score {chosen['score']}/100.",
            metadata={
                "destination_name": chosen["name"],
                "destination_type": "waste_processing_facility",
                "processing_method": chosen.get("processing_method", latest.processing_method),
                "score": chosen["score"],
            },
            commit=False,
        )
        self.db.commit()
        self.db.refresh(saved)
        return saved
