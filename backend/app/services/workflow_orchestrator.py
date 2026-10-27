"""Safe resumable waste orchestration worker backed by a transactional outbox.

The queue is polled by scripts/run_workflow_worker.py; no fake Celery task or
assertion of reliable delivery without running a worker.
"""
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.business import EventOutbox
from app.models.notification import Notification
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.matching_record import MatchingRecord
from app.services.organization_eligibility import eligible_facility, can_profile_action
from app.services.organization_context import select_organization, reset_organization
from app.models.hospital_profile import HospitalProfile
from app.models.user import User
from app.models.roles import UserRole
from app.models.waste_record import WasteRecord
from app.models.waste_enums import WasteStatus, ClassificationConfidence, RiskLevel
from app.models.waste_classification import WasteClassification
from app.models.waste_risk_assessment import WasteRiskAssessment
from app.models.matching_record import MatchingRecord
from app.models.pickup_request import PickupRequestItem
from app.services.waste_classification_service import WasteClassificationService
from app.services.risk_assessment_service import RiskAssessmentService
from app.services.matching_service import MatchingService
from app.services.pickup_service import PickupService
from app.schemas.pickup import PickupRequestCreate


def enqueue_report(db: Session, *, record_id: uuid.UUID, user_id: uuid.UUID):
    """Queue only an authorized user's record, with server-derived ownership.

    The original report transaction also creates its own outbox item. This
    updates that item for older/legacy payloads and for reviewed retries.
    """
    from app.services.waste_service import WasteService
    # This checks active membership and the current per-request org selection.
    record = WasteService(db).get_record(user_id=user_id, record_id=record_id, action='waste_write')
    profile = db.get(HospitalProfile, record.hospital_id)
    payload = {
        'record_id': str(record.id), 'user_id': str(user_id),
        'hospital_id': str(record.hospital_id),
        'organization_id': str(profile.organization_id) if profile.organization_id else None,
    }
    key = f'waste-report:{record_id}'
    item = db.scalar(select(EventOutbox).where(EventOutbox.dedupe_key == key))
    if item is None:
        db.add(EventOutbox(dedupe_key=key, topic='waste.report.progress', payload=payload))
        db.commit()
    elif item.topic == 'waste.report.manual_review' and item.delivered_at is not None:
        # Do not silently requeue without authorization or bypass human gates.
        item.payload = payload
        item.topic = 'waste.report.progress'
        item.delivered_at = None
        item.attempts = 0
        item.last_error = None
        item.last_failed_at = None
        item.dead_lettered_at = None
        db.commit()
    elif item.topic == 'waste.report.progress' and item.delivered_at is None:
        # Existing records may have been enqueued before organization-aware
        # envelopes existed. Update the envelope without creating a second job.
        if item.payload != payload:
            item.payload = payload
            db.commit()


def process_one(db: Session, item: EventOutbox) -> str:
    """Process a report with its verified hospital organization context.

    Never trust the outbox envelope as authorization: resolve the hospital
    from the waste record, verify the envelope matches, and re-check active
    member permissions. Each job resets context even if a stage raises.
    """
    try:
        record_id = uuid.UUID(item.payload['record_id'])
        user_id = uuid.UUID(item.payload['user_id'])
    except (KeyError, TypeError, ValueError, AttributeError):
        return 'manual_review'
    record = db.get(WasteRecord, record_id)
    if record is None:
        return 'manual_review'
    profile = db.get(HospitalProfile, record.hospital_id)
    if profile is None:
        return 'manual_review'

    if 'hospital_id' in item.payload:
        if item.payload['hospital_id'] != str(record.hospital_id):
            return 'manual_review'
    if 'organization_id' in item.payload:
        # In old items the field is absent; derive it from the immutable
        # record -> hospital link instead. A mismatched supplied ID is invalid.
        expected_org = str(profile.organization_id) if profile.organization_id else None
        if item.payload['organization_id'] != expected_org:
            return 'manual_review'

    token = select_organization(str(profile.organization_id) if profile.organization_id else None)
    try:
        user = db.get(User, user_id)
        if user is None or not user.is_active or user.role != UserRole.HOSPITAL:
            return 'manual_review'
        if not can_profile_action(db, profile, user_id, 'HOSPITAL', 'waste_write'):
            return 'manual_review'
        return _process_verified_report(db, record, user_id)
    finally:
        reset_organization(token)


def _process_verified_report(db: Session, record: WasteRecord, user_id: uuid.UUID) -> str:
    """Stage machine; caller guarantees per-job tenant context and access."""
    record_id = record.id
    if record.status == WasteStatus.REPORTED:
        entry=db.scalar(select(WasteClassification).where(WasteClassification.waste_record_id==record_id)
                        .order_by(WasteClassification.created_at.desc()).limit(1))
        if entry is None:
            entry=WasteClassificationService(db).run_classification(user_id=user_id,record_id=record_id)
        if entry.confidence != ClassificationConfidence.HIGH:
            return 'manual_review'
        if not entry.is_confirmed:
            WasteClassificationService(db).confirm_latest(user_id=user_id,record_id=record_id)
        db.refresh(record)
    if record.status == WasteStatus.CLASSIFIED:
        assessment=db.scalar(select(WasteRiskAssessment).where(WasteRiskAssessment.waste_record_id==record_id)
                             .order_by(WasteRiskAssessment.created_at.desc()).limit(1))
        if assessment is None:
            assessment=RiskAssessmentService(db).run_assessment(user_id=user_id,record_id=record_id)
        if assessment.risk_level != RiskLevel.LOW:
            return 'manual_review'
        if not assessment.is_confirmed:
            RiskAssessmentService(db).confirm_latest(user_id=user_id,record_id=record_id)
        db.refresh(record)
    if record.status == WasteStatus.RISK_ASSESSED:
        match=db.scalar(select(MatchingRecord).where(MatchingRecord.waste_record_id==record_id)
                        .order_by(MatchingRecord.created_at.desc()).limit(1))
        if match is None:
            match=MatchingService(db).run_matching(user_id=user_id,record_id=record_id)
        if not match.candidates:
            return 'manual_review'
        if not match.is_confirmed:
            # Existing facility profile verification alone is insufficient
            # for accepting paid commercial treatment work.
            from app.models.facility_profile import TreatmentFacilityProfile
            best_facility = db.get(TreatmentFacilityProfile, uuid.UUID(match.candidates[0]['id']))
            if not eligible_facility(db, best_facility):
                return 'manual_review'
            MatchingService(db).confirm_match(user_id=user_id,record_id=record_id,destination_id=None)
        already=db.scalar(select(PickupRequestItem.id).where(PickupRequestItem.waste_record_id==record_id).limit(1))
        if not already:
            PickupService(db).create_pickup(user_id=user_id,data=PickupRequestCreate(waste_record_ids=[record_id]))
    return 'completed'


def process_receipt_notification(db: Session, item: EventOutbox) -> None:
    """Create the hospital notification in the *same* transaction that ACKs it.

    The envelope is a locator, not an authority.  Re-derive the recipient and
    confirmed treatment facility from durable waste and matching records.
    A deterministic notification primary key also protects against a manual
    replay of a previously acknowledged event.
    """
    if item.topic != 'notification.facility.received':
        raise ValueError('Unexpected receipt notification event topic')
    try:
        record_id = uuid.UUID(item.payload['record_id'])
        facility_id = uuid.UUID(item.payload['facility_id'])
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise ValueError('Invalid receipt notification envelope') from exc
    record = db.get(WasteRecord, record_id)
    if record is None or record.status not in {
        WasteStatus.DESTINATION_RECEIVED, WasteStatus.PROCESSING,
        WasteStatus.PROOF_SUBMITTED, WasteStatus.VERIFIED, WasteStatus.COMPLETED,
    }:
        raise ValueError('Receipt notification requires a received waste batch')
    hospital = db.get(HospitalProfile, record.hospital_id)
    facility = db.get(TreatmentFacilityProfile, facility_id)
    matching = db.scalar(select(MatchingRecord).where(
        MatchingRecord.waste_record_id == record_id,
        MatchingRecord.confirmed_facility_id == facility_id,
        MatchingRecord.is_confirmed.is_(True),
    ).order_by(MatchingRecord.created_at.desc()).limit(1))
    if hospital is None or facility is None or matching is None:
        raise ValueError('Receipt notification has no verified hospital or confirmed facility')
    notification_id = uuid.uuid5(uuid.NAMESPACE_URL, f'medwaste:facility-receipt:{record_id}')
    if db.get(Notification, notification_id) is None:
        db.add(Notification(
            id=notification_id,
            user_id=hospital.user_id,
            title='Waste received by processing facility',
            body=f'{record.waste_code} was received by {facility.name}.',
            waste_record_id=record_id,
        ))
    # No commit here: notification insertion and outbox delivered_at must be
    # committed together by run_workflow_batch or rolled back together.


def run_workflow_batch(db: Session, limit: int = 10) -> dict[str, int]:
    """Claim durable leases BEFORE invoking services that commit their sessions.

    Lease expiry permits crash recovery; idempotent stages and unique constraints
    remain required because arbitrary worker crashes cannot provide exactly-once.
    """
    from sqlalchemy import or_
    now = datetime.now(timezone.utc)
    owner = uuid.uuid4().hex
    rows = list(db.scalars(select(EventOutbox).where(
        EventOutbox.topic.in_(('waste.report.progress', 'notification.facility.received')),
        EventOutbox.delivered_at.is_(None), EventOutbox.attempts < 5,
        or_(EventOutbox.lease_expires_at.is_(None), EventOutbox.lease_expires_at < now),
    ).order_by(EventOutbox.created_at).with_for_update(skip_locked=True, of=EventOutbox).limit(limit)).all())
    keys = [r.id for r in rows]
    for row in rows:
        row.lease_owner = owner
        row.lease_expires_at = now + timedelta(minutes=15)
    db.commit()  # claim survives nested service commits
    result = {'completed': 0, 'manual_review': 0, 'retry': 0}
    for key in keys:
        try:
            row = db.get(EventOutbox, key)
            if row is None or row.lease_owner != owner or row.delivered_at is not None:
                continue
            if row.topic == 'notification.facility.received':
                process_receipt_notification(db, row)
                status = 'completed'
            else:
                status = process_one(db, row)
            row = db.get(EventOutbox, key)
            if row is None or row.lease_owner != owner:
                continue
            if status == 'manual_review':
                row.topic = 'waste.report.manual_review'
            row.delivered_at = datetime.now(timezone.utc)
            row.lease_owner = None
            row.lease_expires_at = None
            result[status] += 1
            db.commit()
        except Exception as exc:
            db.rollback()
            row = db.get(EventOutbox, key)
            if row is not None and row.lease_owner == owner:
                row.attempts += 1
                row.last_failed_at = datetime.now(timezone.utc)
                # Error class only: exception messages might include secrets,
                # hospital-identifying input or untrusted response content.
                row.last_error = type(exc).__name__[:320]
                row.lease_owner = None
                row.lease_expires_at = None
                if row.attempts >= 5:
                    row.topic = ('notification.facility.received.dead_letter'
                                 if row.topic == 'notification.facility.received'
                                 else 'waste.report.dead_letter')
                    row.dead_lettered_at = row.last_failed_at
                result['retry'] += 1
                db.commit()
    return result
