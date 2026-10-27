from app.schemas.audit_reason import meaningful_reason
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.api.deps import require_roles
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.models.waste_category import WasteCategory
from app.models.waste_record import WasteRecord
from app.models.pickup_request import PickupRequest
from app.models.waste_enums import PickupStatus
from app.models.route import Route, RouteStop, RouteStatus, RouteStopStatus
from app.models.vehicle import Vehicle
from app.models.business import EventOutbox
from app.models.audit_log import AuditLog
from pydantic import BaseModel, Field, field_validator
from app.models.hospital_profile import HospitalProfile
from app.schemas.admin import *
from app.services.admin_service import AdminService

router=APIRouter(prefix="/admin", tags=["admin"])
require_admin=require_roles(UserRole.ADMIN)

@router.get("/overview", response_model=AdminOverviewResponse)
def overview(current_user: User=Depends(require_admin), db: Session=Depends(get_db)): return AdminService(db).overview()

@router.get("/users", response_model=list[AdminUserResponse])
def users(role: UserRole|None=Query(None), current_user: User=Depends(require_admin), db: Session=Depends(get_db)): return AdminService(db).users(role)

@router.patch("/users/{user_id}", response_model=AdminUserResponse)
def update_user(user_id: uuid.UUID, payload: AdminUserUpdate, current_user: User=Depends(require_admin), db: Session=Depends(get_db)):
    try: obj=AdminService(db).update_user(current_user,user_id,payload.is_active,payload.is_verified)
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc))
    if not obj: raise HTTPException(status_code=404, detail="User not found.")
    return obj

@router.get("/verification/{role}", response_model=VerificationListResponse)
def verification(role: UserRole, pending_only: bool=True, current_user: User=Depends(require_admin), db: Session=Depends(get_db)):
    if role == UserRole.ADMIN: raise HTTPException(400,"Admin accounts do not require organization verification.")
    items,total=AdminService(db).verification_list(role,pending_only); return {"items":items,"total":total}

@router.patch("/verification/{role}/{profile_id}")
def set_verification(role: UserRole, profile_id: uuid.UUID, verified: bool, current_user: User=Depends(require_admin), db: Session=Depends(get_db)):
    if role == UserRole.ADMIN: raise HTTPException(400,"Invalid verification role.")
    obj=AdminService(db).set_verification(current_user,role,profile_id,verified)
    if not obj: raise HTTPException(404,"Verification target not found.")
    return {"id": str(profile_id), "is_verified": verified}

@router.get("/categories", response_model=list[CategoryAdminResponse])
def categories(current_user: User=Depends(require_admin), db: Session=Depends(get_db)): return AdminService(db).repo.category_list()

@router.post("/categories", response_model=CategoryAdminResponse, status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate,current_user: User=Depends(require_admin),db: Session=Depends(get_db)):
    try:return AdminService(db).create_category(current_user,payload)
    except ValueError as exc:raise HTTPException(409,str(exc))

@router.patch("/categories/{category_id}", response_model=CategoryAdminResponse)
def update_category(category_id: uuid.UUID,payload: CategoryUpdate,current_user: User=Depends(require_admin),db: Session=Depends(get_db)):
    try: obj=AdminService(db).update_category(current_user,category_id,payload)
    except ValueError as exc: raise HTTPException(409, str(exc))
    if not obj: raise HTTPException(404,"Category not found.")
    return obj

@router.get("/risk-rules", response_model=list[RiskRuleAdminResponse])
def risk_rules(current_user: User=Depends(require_admin),db: Session=Depends(get_db)):
    return [{"id":r.id,"category_id":r.category_id,"category_name":c.name,"base_risk_level":r.base_risk_level,"quantity_escalation_threshold":r.quantity_escalation_threshold,"is_active":r.is_active,"updated_at":r.updated_at} for r,c in AdminService(db).risk_rules()]

@router.put("/risk-rules/{category_id}", response_model=RiskRuleAdminResponse)
def update_risk_rule(category_id: uuid.UUID,payload: RiskRuleUpdate,current_user: User=Depends(require_admin),db: Session=Depends(get_db)):
    service=AdminService(db)
    try:
        obj=service.update_risk_rule(current_user,category_id,payload)
    except ValueError as exc:
        raise HTTPException(404,str(exc))
    category=db.get(WasteCategory,category_id)
    return {"id":obj.id,"category_id":obj.category_id,"category_name":category.name,"base_risk_level":obj.base_risk_level,"quantity_escalation_threshold":obj.quantity_escalation_threshold,"is_active":obj.is_active,"updated_at":obj.updated_at}

@router.get("/incidents", response_model=list[IncidentAdminResponse])
def incidents(open_only: bool=False,current_user: User=Depends(require_admin),db: Session=Depends(get_db)):
    return [{"id":i.id,"waste_record_id":w.id,"waste_code":w.waste_code,"incident_type":i.incident_type,"severity":i.severity,"description":i.description,"is_resolved":i.is_resolved,"created_at":i.created_at} for i,w in AdminService(db).incidents(open_only)]

@router.patch("/incidents/{incident_id}", response_model=IncidentAdminResponse)
def resolve_incident(incident_id: uuid.UUID,payload: IncidentResolveRequest,current_user: User=Depends(require_admin),db: Session=Depends(get_db)):
    obj=AdminService(db).resolve_incident(current_user,incident_id,payload.is_resolved)
    if not obj: raise HTTPException(404,"Incident not found.")
    waste=db.get(WasteRecord,obj.waste_record_id)
    return {"id":obj.id,"waste_record_id":obj.waste_record_id,"waste_code":waste.waste_code,"incident_type":obj.incident_type,"severity":obj.severity,"description":obj.description,"is_resolved":obj.is_resolved,"created_at":obj.created_at}

@router.get("/audit-logs", response_model=list[AuditLogResponse])
def audit_logs(limit:int=Query(100,ge=1,le=500),current_user: User=Depends(require_admin),db: Session=Depends(get_db)):
    return [{"id":a.id,"actor_user_id":a.actor_user_id,"actor_name":u.full_name if u else None,"action":a.action,"entity_type":a.entity_type,"entity_id":a.entity_id,"details":a.details,"created_at":a.created_at} for a,u in AdminService(db).audit_logs(limit)]


@router.get('/pickup-arrival-exception-candidates')
def pickup_arrival_exception_candidates(
    current_user: User = Depends(require_admin), db: Session = Depends(get_db),
):
    """Active, en-route pickups eligible for independent no-GPS review.

    Read-only discovery; this list does NOT approve arrival or expose the
    confidential hospital handover QR. POST approval is still separately
    authorized, audited and limited to 20 minutes.
    """
    rows = db.execute(
        select(PickupRequest, RouteStop, Vehicle, HospitalProfile)
        .join(RouteStop, RouteStop.pickup_id == PickupRequest.id)
        .join(Route, Route.id == RouteStop.route_id)
        .join(Vehicle, Vehicle.id == Route.vehicle_id)
        .join(HospitalProfile, HospitalProfile.id == PickupRequest.hospital_id)
        .where(
            PickupRequest.status == PickupStatus.ASSIGNED,
            PickupRequest.assigned_vehicle_id == Vehicle.id,
            PickupRequest.assigned_collector_id == Vehicle.assigned_collector_id,
            Route.status == RouteStatus.ACTIVE,
            RouteStop.status == RouteStopStatus.EN_ROUTE,
        )
        .order_by(RouteStop.estimated_arrival_at, RouteStop.created_at)
        .limit(100)
    ).all()
    def pending_request(pickup, stop):
        from datetime import datetime, timedelta, timezone
        query = select(AuditLog).where(
            AuditLog.action == 'pickup.arrival.exception_requested',
            AuditLog.entity_type == 'pickup', AuditLog.entity_id == str(pickup.id),
            AuditLog.actor_user_id == pickup.assigned_collector_id,
            AuditLog.created_at >= datetime.now(timezone.utc) - timedelta(hours=1),
        ).order_by(AuditLog.created_at.desc()).limit(20)
        for audit in db.scalars(query):
            if (audit.details or {}).get('route_stop_id') == str(stop.id):
                return audit
        return None

    def candidate(pickup, stop, vehicle, hospital):
        requested = pending_request(pickup, stop)
        return {
            'pickup_id': str(pickup.id),
            'stop_id': str(stop.id),
            'hospital_name': hospital.name,
            'vehicle_code': vehicle.vehicle_code,
            'assigned_driver_id': str(pickup.assigned_collector_id),
            'estimated_arrival_at': stop.estimated_arrival_at.isoformat() if stop.estimated_arrival_at else None,
            'driver_requested_at': requested.created_at.isoformat() if requested else None,
            'driver_reported_reason': (requested.details or {}).get('reason') if requested else None,
        }
    return [candidate(pickup, stop, vehicle, hospital) for pickup, stop, vehicle, hospital in rows]


class DeadLetterRetryRequest(BaseModel):
    reason: str = Field(min_length=12, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_meaningful_reason(cls, value: str) -> str:
        return meaningful_reason(value, minimum=12)


@router.get('/workflow/dead-letters')
def list_workflow_dead_letters(limit: int = Query(100, ge=1, le=200),
    current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Admin-only failure visibility. Never expose raw worker exceptions."""
    rows = db.scalars(select(EventOutbox).where(
        EventOutbox.topic.in_(('waste.report.dead_letter',
                                'notification.facility.received.dead_letter')),
    ).order_by(EventOutbox.dead_lettered_at.desc()).limit(limit)).all()
    return [{
        'id': str(row.id), 'dedupe_key': row.dedupe_key, 'topic': row.topic,
        'record_id': row.payload.get('record_id') if isinstance(row.payload, dict) else None,
        'attempts': row.attempts, 'last_error': row.last_error,
        'last_failed_at': row.last_failed_at, 'dead_lettered_at': row.dead_lettered_at,
    } for row in rows]


@router.post('/workflow/dead-letters/{event_id}/requeue')
def requeue_workflow_dead_letter(event_id: uuid.UUID, payload: DeadLetterRetryRequest,
    current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Audited explicit retry. process_one re-verifies record/tenant permissions."""
    row = db.scalar(select(EventOutbox).where(EventOutbox.id == event_id).with_for_update(of=EventOutbox))
    if row is None:
        raise HTTPException(404, 'Workflow event not found')
    retry_topics = {
        'waste.report.dead_letter': 'waste.report.progress',
        'notification.facility.received.dead_letter': 'notification.facility.received',
    }
    if row.topic not in retry_topics or row.delivered_at is not None:
        raise HTTPException(409, 'Only failed dead-letter workflow events can be requeued')
    if row.lease_owner is not None:
        raise HTTPException(409, 'Workflow event is currently leased')
    previous_error = row.last_error
    previous_attempts = row.attempts
    row.topic = retry_topics[row.topic]
    row.attempts = 0
    row.dead_lettered_at = None
    row.last_error = None
    row.last_failed_at = None
    row.lease_expires_at = None
    db.add(AuditLog(actor_user_id=current_user.id, action='workflow.dead_letter.requeue',
        entity_type='event_outbox', entity_id=str(row.id), details={
            'reason': payload.reason.strip(), 'previous_error': previous_error,
            'previous_attempts': previous_attempts,
        }))
    db.commit()
    return {'id': str(row.id), 'status': 'queued', 'attempts': row.attempts}
