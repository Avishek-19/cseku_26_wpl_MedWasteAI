import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.processing_record import ProcessingRecord
from app.models.business import Organization, OperatorJobEvent
from app.services.organization_eligibility import eligible_facility, profile_organization
from app.models.route import Route, RouteStop
from app.models.waste_enums import WasteEventType, WasteStatus
from app.models.pickup_request import PickupRequest, PickupRequestItem
from app.repositories.facility_repository import FacilityRepository
from app.repositories.matching_repository import MatchingRepository
from app.repositories.processing_repository import ProcessingRepository
from app.repositories.waste_record_repository import WasteRecordRepository
from app.services.waste_event_service import WasteEventService
from app.services.quantity_service import quantity_to_kg
from app.realtime.tracking_manager import tracking_manager, route_topic, vehicle_topic

class ProcessingNotFoundError(Exception): pass
class ProcessingStateError(Exception): pass
class ProcessingMethodNotAllowedError(Exception): pass
class FacilityNotAuthorizedError(Exception): pass

class ProcessingService:
    def __init__(self, db: Session):
        self.db=db; self.facilities=FacilityRepository(db); self.matches=MatchingRepository(db); self.records=WasteRecordRepository(db); self.processing=ProcessingRepository(db); self.events=WasteEventService(db)

    def _context(self, user_id, record_id):
        facility=self.facilities.get_by_user_id(user_id)
        if facility is None or not eligible_facility(self.db, facility): raise FacilityNotAuthorizedError()
        facility = self.db.scalar(select(type(facility)).where(type(facility).id == facility.id)
            .with_for_update(of=type(facility)).execution_options(populate_existing=True))
        from app.models.waste_record import WasteRecord
        record=self.db.scalar(select(WasteRecord).where(WasteRecord.id == record_id)
            .with_for_update(of=WasteRecord).execution_options(populate_existing=True))
        if record is None: raise ProcessingNotFoundError()
        match=self.matches.get_confirmed_for_record(record_id)
        if match is None or match.confirmed_facility_id != facility.id: raise FacilityNotAuthorizedError()
        return facility, record

    def _is_demo_record(self, record_id):
        from app.models.audit_log import AuditLog
        return self.db.scalar(select(AuditLog.id).where(
            AuditLog.action == "facility.receipt.demo_manual",
            AuditLog.entity_type == "waste", AuditLog.entity_id == str(record_id)
        ).limit(1)) is not None

    def _broadcast_waste_status(self, record, event_name: str, actor_user_id):
        from app.models.route import RouteStop
        from app.models.pickup_request import PickupRequest, PickupRequestItem
        route = self.db.scalar(
            select(Route)
            .join(RouteStop, RouteStop.route_id == Route.id)
            .join(PickupRequest, PickupRequest.id == RouteStop.pickup_id)
            .join(PickupRequestItem, PickupRequestItem.pickup_request_id == PickupRequest.id)
            .where(PickupRequestItem.waste_record_id == record.id)
            .order_by(Route.version.desc())
        )
        if route:
            tracking_manager.broadcast_from_sync(
                {
                    "type": "status_update",
                    "event": event_name,
                    "waste_record_id": str(record.id),
                    "waste_status": record.status.value,
                    "route_id": str(route.id),
                    "vehicle_id": str(route.vehicle_id),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "actor_user_id": str(actor_user_id),
                },
                {route_topic(route.id), vehicle_topic(route.vehicle_id)},
            )

    def get(self, user_id, record_id):
        facility, _=self._context(user_id, record_id)
        item=self.processing.get_for_waste(record_id)
        if item and item.facility_id != facility.id: raise FacilityNotAuthorizedError()
        return item

    def start(self, user_id, record_id, method):
        from app.services.organization_eligibility import can_profile_action
        profile = self.facilities.get_by_user_id(user_id)
        if not can_profile_action(self.db, profile, user_id, 'TREATMENT_FACILITY', 'facility_process'):
            raise FacilityNotAuthorizedError()

        facility, record=self._context(user_id, record_id)
        if record.status != WasteStatus.DESTINATION_RECEIVED: raise ProcessingStateError("Waste must be received before processing starts.")
        allowed=[str(x).upper() for x in (facility.processing_services or [])]
        if method.upper() not in allowed: raise ProcessingMethodNotAllowedError()
        match=self.matches.get_confirmed_for_record(record_id)
        if match is None or not match.processing_method or method.upper() != match.processing_method.upper():
            raise ProcessingMethodNotAllowedError()
        item=self.processing.get_for_waste(record_id)
        if item is not None: raise ProcessingStateError("Processing has already been started for this batch.")
        item=ProcessingRecord(waste_record_id=record_id, facility_id=facility.id, processing_method=method.upper(), status="processing", started_at=datetime.now(timezone.utc))
        record.status=WasteStatus.PROCESSING
        self.db.add(item); self.db.flush()
        self.events.record(waste_record_id=record.id,event_type=WasteEventType.PROCESSING,status_snapshot=WasteStatus.PROCESSING,actor_user_id=user_id,quantity=record.received_quantity or record.quantity,notes=f"{'SIMULATED: ' if self._is_demo_record(record.id) else ''}Processing started using {method.upper()}.",metadata={"processing_method":method.upper(),"facility_name":facility.name,"simulated":self._is_demo_record(record.id)}, commit=False)
        self.db.commit(); self.db.refresh(item)
        self._broadcast_waste_status(record, "waste.processing.started", user_id)
        return item

    def submit_proof(self, user_id, record_id, proof_note):
        from app.services.organization_eligibility import can_profile_action
        profile = self.facilities.get_by_user_id(user_id)
        if not can_profile_action(self.db, profile, user_id, 'TREATMENT_FACILITY', 'facility_process'):
            raise FacilityNotAuthorizedError()

        facility, record=self._context(user_id, record_id)
        item=self.processing.get_for_waste(record_id)
        if item is None or item.facility_id != facility.id: raise ProcessingNotFoundError()
        if item.status != "processing": raise ProcessingStateError("Processing must be active before proof can be submitted.")
        item.status="proof_submitted"; item.proof_note=proof_note; item.proof_submitted_at=datetime.now(timezone.utc)
        record.status = WasteStatus.PROOF_SUBMITTED
        self.db.flush()
        self.events.record(waste_record_id=record.id,event_type=WasteEventType.PROOF_SUBMITTED,status_snapshot=WasteStatus.PROOF_SUBMITTED,actor_user_id=user_id,quantity=record.received_quantity or record.quantity,notes=f"{'SIMULATED: ' if self._is_demo_record(record.id) else ''}Facility processing report: {proof_note}",metadata={"processing_method":item.processing_method,"report_available":True,"simulated":self._is_demo_record(record.id)}, commit=False)
        self.db.commit(); self.db.refresh(item)
        self._broadcast_waste_status(record, "waste.processing.proof_submitted", user_id)
        return item

    def complete(self, user_id, record_id):
        from app.services.organization_eligibility import can_profile_action
        profile = self.facilities.get_by_user_id(user_id)
        if not can_profile_action(self.db, profile, user_id, 'TREATMENT_FACILITY', 'facility_process'):
            raise FacilityNotAuthorizedError()

        facility, record=self._context(user_id, record_id)
        item=self.processing.get_for_waste(record_id)
        if item is None or item.facility_id != facility.id: raise ProcessingNotFoundError()
        if item.status != "proof_submitted": raise ProcessingStateError("Submit processing proof before completing the batch.")
        item.status="completed"; item.completed_at=datetime.now(timezone.utc); record.status=WasteStatus.VERIFIED
        received = Decimal(str(record.received_quantity or record.quantity))
        received_kg = quantity_to_kg(received, record.unit) or Decimal("0")
        facility.current_utilization_kg = max(Decimal("0"), Decimal(str(facility.current_utilization_kg)) - received_kg)
        self.db.flush()
        self.events.record(waste_record_id=record.id,event_type=WasteEventType.VERIFIED,status_snapshot=WasteStatus.VERIFIED,actor_user_id=user_id,quantity=received,notes=f"{'SIMULATED: ' if self._is_demo_record(record.id) else ''}Processing verified by facility.",metadata={"processing_method":item.processing_method,"simulated":self._is_demo_record(record.id)}, commit=False)
        record.status=WasteStatus.COMPLETED
        self.events.record(waste_record_id=record.id,event_type=WasteEventType.COMPLETED,status_snapshot=WasteStatus.COMPLETED,actor_user_id=user_id,quantity=received,notes=f"{'SIMULATED: ' if self._is_demo_record(record.id) else ''}Waste processing workflow completed.",metadata={"processing_method":item.processing_method,"simulated":self._is_demo_record(record.id)}, commit=False)
        # Count completed/verified work once per operator (not at assignment).
        # The shared record ID is a stable auditable job reference.
        facility_org = profile_organization(self.db, facility, 'TREATMENT_FACILITY')
        pickup = self.db.scalar(select(PickupRequest).join(PickupRequestItem,
            PickupRequestItem.pickup_request_id == PickupRequest.id).where(
            PickupRequestItem.waste_record_id == record.id).limit(1))
        collector_org_id = None
        if pickup and pickup.assigned_vehicle_id:
            from app.models.vehicle import Vehicle
            vehicle = self.db.get(Vehicle, pickup.assigned_vehicle_id)
            collector_org_id = vehicle.organization_id if vehicle else None
        for org_id in (facility_org.id if facility_org else None, collector_org_id):
            if org_id and not self.db.scalar(select(OperatorJobEvent.id).where(
                OperatorJobEvent.organization_id == org_id,
                OperatorJobEvent.job_reference == str(record.id)).limit(1)):
                self.db.add(OperatorJobEvent(organization_id=org_id,
                    job_reference=str(record.id)))
        self.db.commit(); self.db.refresh(item)
        self._broadcast_waste_status(record, "waste.processing.completed", user_id)
        return item