from app.schemas.audit_reason import meaningful_reason
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from decimal import Decimal
import base64
from io import BytesIO
import qrcode
from qrcode.image.svg import SvgPathImage
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_roles
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.models.waste_enums import PickupStatus
from app.models.route import Route, RouteStatus, RouteStop
from app.models.matching_record import MatchingRecord
from app.models.pickup_request import PickupRequest, PickupRequestItem
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.hospital_profile import HospitalProfile
from app.models.vehicle import Vehicle
from app.schemas.pickup import (
    PickupCancelRequest,
    PickupRequestCreate,
    PickupRequestListResponse,
    PickupRequestResponse,
    pickup_to_response,
)
from app.services.pickup_service import (
    NotAssignedCollectorError,
    PickupNotAssignableError,
    PickupNotCancellableError,
    PickupNotCollectableError,
    PickupWeightValidationError,
    PickupNotFoundError,
    PickupNotInTransitableError,
    PickupService,
    WasteRecordNotEligibleError,
    DestinationNotConfirmedError,
)
from app.services.waste_service import HospitalProfileRequiredError, WasteRecordNotFoundError

router = APIRouter(prefix="/pickups", tags=["pickups"])

class ArriveRequest(BaseModel):
    handover_qr: str = Field(min_length=20, max_length=128)
    no_gps_reason: str | None = Field(default=None, max_length=500)

@router.get("/demo-manual-mode")
def demo_manual_mode(current_user: User = Depends(get_current_user)):
    from app.core.config import get_settings
    cfg = get_settings()
    return {"enabled": cfg.enable_demo_manual_workflow and cfg.environment.lower() in {"development", "test"}}

class HandoverRequest(BaseModel):
    handover_qr: str = Field(min_length=20, max_length=128)
    actual_weight_kg: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    packaging_condition: str = Field(pattern="^(sealed|damaged|exception)$")
    exception_reason: str | None = Field(default=None, max_length=500)

@router.get("/{pickup_id}/handover-qr")
def hospital_handover_qr(pickup_id: UUID, response: Response,
                         current_user: User = Depends(require_roles(UserRole.HOSPITAL)),
                         db: Session = Depends(get_db)):
    try:
        pickup = PickupService(db).get_pickup(user_id=current_user.id, pickup_id=pickup_id)
    except HospitalProfileRequiredError:
        raise _profile_required()
    except PickupNotFoundError:
        raise _not_found()
    except PermissionError:
        raise HTTPException(status_code=403, detail="Hospital does not have access to this pickup.")
    if pickup.status != PickupStatus.ASSIGNED or not pickup.assigned_collector_id or not pickup.handover_token:
        raise HTTPException(status_code=409, detail="QR is available only for an assigned pickup.")
    # Prevent HTTP/proxy caches from retaining sensitive handover references.
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=3, box_size=8)
    qr.add_data(pickup.handover_token)
    qr.make(fit=True)
    stream = BytesIO()
    qr.make_image(image_factory=SvgPathImage).save(stream)
    return {"handover_qr": pickup.handover_token,
            "qr_svg_data_url": "data:image/svg+xml;base64," + base64.b64encode(stream.getvalue()).decode("ascii"),
            "pickup_id": str(pickup.id),
            "warning": "Hand this reference to the assigned driver only at physical handover."}

@router.post("/{pickup_id}/arrive")
def arrive_pickup(pickup_id: UUID, payload: ArriveRequest,
                  current_user: User = Depends(require_roles(UserRole.COLLECTOR)), db: Session = Depends(get_db)):
    try:
        stop = PickupService(db).mark_arrived(collector_id=current_user.id, pickup_id=pickup_id,
            token=payload.handover_qr, manual_reason=payload.no_gps_reason)
        return {"stop_id": str(stop.id), "status": stop.status.value}
    except (PickupNotFoundError, NotAssignedCollectorError):
        raise HTTPException(status_code=404, detail="Pickup not found or not assigned to you.")
    except PickupNotCollectableError:
        raise HTTPException(status_code=409, detail="Arrival not verified: trusted GPS or separate admin-approved no-GPS exception and hospital QR required.")


@router.post("/{pickup_id}/demo-arrive")
def demo_arrive_pickup(pickup_id: UUID, payload: ArriveRequest,
                       current_user: User = Depends(require_roles(UserRole.COLLECTOR)),
                       db: Session = Depends(get_db)):
    from app.core.config import get_settings
    cfg = get_settings()
    if not cfg.enable_demo_manual_workflow or cfg.environment.lower() not in {"development", "test"}:
        raise HTTPException(status_code=404, detail="Demo workflow disabled")
    try:
        stop = PickupService(db).mark_arrived(
            collector_id=current_user.id, pickup_id=pickup_id,
            token=payload.handover_qr, demo_manual=True)
        return {"stop_id": str(stop.id), "status": stop.status.value,
                "simulated": True, "message": "SIMULATED manual arrival; not real GPS evidence"}
    except (PickupNotFoundError, NotAssignedCollectorError):
        raise HTTPException(status_code=404, detail="Pickup not found or not assigned to this driver")
    except PickupNotCollectableError:
        raise HTTPException(status_code=409, detail="Active en-route stop and correct hospital QR required")

class ArrivalExceptionApproval(BaseModel):
    reason: str = Field(min_length=12, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_meaningful_reason(cls, value: str) -> str:
        return meaningful_reason(value, minimum=12)


class ArrivalExceptionRequest(BaseModel):
    reason: str = Field(min_length=12, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_meaningful_reason(cls, value: str) -> str:
        return meaningful_reason(value, minimum=12)


@router.post("/{pickup_id}/arrival-exception-request")
def request_no_gps_arrival(pickup_id: UUID, payload: ArrivalExceptionRequest,
                           current_user: User = Depends(require_roles(UserRole.COLLECTOR)),
                           db: Session = Depends(get_db)):
    """Driver may request independent review, NEVER self-approve arrival.

    Browser geolocation has no server-verifiable HMAC device key. Admin approval
    remains separate and hospital QR is still required at handover.
    """
    from app.models.audit_log import AuditLog
    from app.models.route import RouteStopStatus
    from datetime import datetime, timezone
    pickup = db.get(PickupRequest, pickup_id)
    if pickup is None or pickup.assigned_collector_id != current_user.id:
        raise HTTPException(404, "No pickup assigned to this collector.")
    if pickup.status != PickupStatus.ASSIGNED:
        raise HTTPException(409, "Pickup is not awaiting arrival.")
    stop = db.scalar(select(RouteStop).join(Route).where(
        RouteStop.pickup_id == pickup_id, Route.status == RouteStatus.ACTIVE,
        Route.vehicle_id == pickup.assigned_vehicle_id,
        RouteStop.status == RouteStopStatus.EN_ROUTE,
    ).limit(1))
    if stop is None:
        raise HTTPException(409, "Active en-route stop required for supervisor review.")
    db.add(AuditLog(actor_user_id=current_user.id,
        action="pickup.arrival.exception_requested", entity_type="pickup", entity_id=str(pickup_id),
        details={"reason": payload.reason, "route_stop_id": str(stop.id),
                 "driver_id": str(current_user.id), "requested_at": datetime.now(timezone.utc).isoformat()}))
    db.commit()
    return {"requested": True, "approved": False, "pickup_id": str(pickup_id),
            "message": "Supervisor must independently verify arrival and approve. Hospital QR remains required."}


@router.post("/{pickup_id}/arrival-exception-approval")
def approve_no_gps_arrival(pickup_id: UUID, payload: ArrivalExceptionApproval,
                          current_user: User = Depends(require_roles(UserRole.ADMIN)),
                          db: Session = Depends(get_db)):
    """Separate, audited supervisor authorization; driver still needs hospital QR."""
    from app.models.audit_log import AuditLog
    from app.models.route import RouteStopStatus
    from datetime import datetime, timezone
    pickup = db.get(PickupRequest, pickup_id)
    if not pickup or pickup.status != PickupStatus.ASSIGNED:
        raise HTTPException(status_code=404, detail="No active assigned pickup.")
    stop = db.scalar(select(RouteStop).join(Route).where(
        RouteStop.pickup_id == pickup_id, Route.status == RouteStatus.ACTIVE,
        Route.vehicle_id == pickup.assigned_vehicle_id,
        RouteStop.status == RouteStopStatus.EN_ROUTE,
    ).limit(1).with_for_update(of=RouteStop))
    if stop is None:
        raise HTTPException(status_code=409, detail="Stop must be en route for manual arrival approval.")
    audit = AuditLog(actor_user_id=current_user.id,
        action="pickup.arrival.exception_approved", entity_type="pickup", entity_id=str(pickup_id),
        details={"reason": payload.reason.strip(), "route_stop_id": str(stop.id),
                 "driver_id": str(pickup.assigned_collector_id),
                 "approved_at": datetime.now(timezone.utc).isoformat()})
    db.add(audit)
    db.commit()
    return {"approved": True, "pickup_id": str(pickup_id),
            "valid_for_seconds": 1200, "requires_hospital_qr": True}


require_hospital = require_roles(UserRole.HOSPITAL)
require_collector = require_roles(UserRole.COLLECTOR)


def _profile_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_412_PRECONDITION_FAILED,
        detail="Complete your hospital profile first.",
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pickup request not found.")


@router.post("", response_model=PickupRequestResponse, status_code=status.HTTP_201_CREATED)
def create_pickup(
    payload: PickupRequestCreate,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        pickup = PickupService(db).create_pickup(user_id=current_user.id, data=payload)
    except HospitalProfileRequiredError:
        raise _profile_required()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except WasteRecordNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waste record not found.")
    except DestinationNotConfirmedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{exc.waste_code} has no confirmed Waste Processing Facility. "
                "Run matching and confirm a facility before requesting pickup."
            ),
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except WasteRecordNotEligibleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{exc.waste_code} isn't eligible for pickup — it must be risk-assessed and not "
                "already part of another active pickup."
            ),
        )
    return pickup_to_response(pickup, db)


@router.get("", response_model=PickupRequestListResponse)
def list_pickups(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: PickupStatus | None = Query(default=None, alias="status"),
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        items, total = PickupService(db).search_pickups(
            user_id=current_user.id, page=page, page_size=page_size, status=status_filter
        )
    except HospitalProfileRequiredError:
        raise _profile_required()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    total_pages = max(1, (total + page_size - 1) // page_size)
    return PickupRequestListResponse(
        items=[pickup_to_response(p, db) for p in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/assigned", response_model=list[PickupRequestResponse])
def list_assigned_pickups(
    scope: str = Query(default="personal", pattern="^(personal|company)$"),
    current_user: User = Depends(require_collector),
    db: Session = Depends(get_db),
):
    if scope == "personal":
        pickups = PickupService(db).list_assigned_for_collector(current_user.id)
    else:
        from app.models.business import OrganizationMember
        from app.services.organization_context import selected_org_id
        org_ids = select(OrganizationMember.organization_id).where(
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.active.is_(True),
            OrganizationMember.member_role.in_(['owner', 'manager', 'dispatcher'])
        )
        stmt = select(PickupRequest).join(Vehicle, Vehicle.id == PickupRequest.assigned_vehicle_id).where(
            PickupRequest.status.in_([PickupStatus.ASSIGNED, PickupStatus.COLLECTED, PickupStatus.IN_TRANSIT]),
            Vehicle.organization_id.in_(org_ids)
        )
        if selected_org_id() is not None:
            stmt = stmt.where(Vehicle.organization_id == selected_org_id())
        pickups = list(db.scalars(stmt.order_by(PickupRequest.scheduled_at)).all())
    return [pickup_to_response(p, db) for p in pickups]


# ★★★ IMPORTANT: static path MUST be registered BEFORE /{pickup_id} ★★★
@router.get("/transfers/history")
def transfer_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_collector),
    db: Session = Depends(get_db),
):
    """Persisted Hospital → Treatment Facility transport history for a collector."""
    stmt = (
        select(Route)
        .join(Vehicle, Vehicle.id == Route.vehicle_id)
        .where(
            Route.status == RouteStatus.COMPLETED,
            Vehicle.assigned_collector_id == current_user.id,
        )
        .order_by(Route.completed_at.desc().nullslast(), Route.version.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    routes = list(db.scalars(stmt).all())
    items = []

    for route in routes:
        stops = list(
            db.scalars(
                select(RouteStop)
                .where(RouteStop.route_id == route.id)
                .order_by(RouteStop.sequence)
            ).all()
        )
        waste_ids: list[str] = []
        hospital_names: list[str] = []
        facility_ids: set = set()
        collected_times: list = []
        received_at = route.destination_received_at

        for stop in stops:
            pickup = db.execute(
                select(PickupRequest)
                .options(
                    selectinload(PickupRequest.items).selectinload(PickupRequestItem.waste_record)
                )
                .where(PickupRequest.id == stop.pickup_id)
            ).scalar_one_or_none()

            if not pickup:
                continue

            hospital = db.get(HospitalProfile, pickup.hospital_id)
            if hospital and hospital.name not in hospital_names:
                hospital_names.append(hospital.name)

            if pickup.collected_at is not None:
                collected_times.append(pickup.collected_at)

            for item in pickup.items:
                waste_ids.append(str(item.waste_record_id))
                match = db.scalar(
                    select(MatchingRecord)
                    .where(
                        MatchingRecord.waste_record_id == item.waste_record_id,
                        MatchingRecord.is_confirmed.is_(True),
                    )
                    .order_by(MatchingRecord.confirmed_at.desc())
                )
                if match and match.confirmed_facility_id:
                    facility_ids.add(match.confirmed_facility_id)

                record = item.waste_record
                if record is not None and record.received_at is not None:
                    if received_at is None or record.received_at > received_at:
                        received_at = record.received_at

        facility = None
        if len(facility_ids) == 1:
            facility = db.get(TreatmentFacilityProfile, next(iter(facility_ids)))

        vehicle = db.get(Vehicle, route.vehicle_id)

        items.append(
            {
                "transfer_id": str(route.id),
                "route_id": str(route.id),
                "route_version": route.version,
                "hospital": ", ".join(hospital_names) or "Hospital",
                "facility": facility.name if facility else "Treatment Facility",
                "facility_id": str(facility.id) if facility else None,
                "vehicle": vehicle.vehicle_code if vehicle else None,
                "collector_id": str(current_user.id),
                "waste_ids": sorted(set(waste_ids)),
                "collected_at": min(collected_times) if collected_times else None,
                "destination_arrived_at": route.destination_arrived_at,
                "received_at": received_at,
                "distance_km": float(route.total_distance_km)
                if route.total_distance_km is not None
                else None,
                "duration_minutes": route.estimated_duration_minutes,
                "status": "completed",
            }
        )

    return {"items": items, "page": page, "page_size": page_size, "count": len(items)}


@router.get("/{pickup_id}", response_model=PickupRequestResponse)
def get_pickup(
    pickup_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = PickupService(db)
    if current_user.role == UserRole.HOSPITAL:
        try:
            pickup = service.get_pickup(user_id=current_user.id, pickup_id=pickup_id)
        except HospitalProfileRequiredError:
            raise _profile_required()
        except PickupNotFoundError:
            raise _not_found()
    elif current_user.role == UserRole.COLLECTOR:
        pickup = service.pickups.get_by_id(pickup_id)
        if pickup is None or pickup.assigned_collector_id != current_user.id:
            raise _not_found()
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted.")
    return pickup_to_response(pickup, db)


@router.post("/{pickup_id}/cancel", response_model=PickupRequestResponse)
def cancel_pickup(
    pickup_id: UUID,
    payload: PickupCancelRequest,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    # Snapshot the affected active route before the transactional cancellation.
    # After a last-stop cancellation it is intentionally no longer ACTIVE.
    affected_route = db.scalar(select(Route).join(RouteStop).where(
        RouteStop.pickup_id == pickup_id,
        Route.status == RouteStatus.ACTIVE,
    ).limit(1))
    try:
        pickup = PickupService(db).cancel_pickup(
            user_id=current_user.id, pickup_id=pickup_id, reason=payload.reason
        )
    except HospitalProfileRequiredError:
        raise _profile_required()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except PickupNotFoundError:
        raise _not_found()
    except PickupNotCancellableError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This pickup can no longer be cancelled.",
        )
    # Publish only after the entire pickup + route + tracking transaction commits.
    # The driver and live-ops dashboards must not continue following a deleted stop.
    from app.realtime.tracking_manager import tracking_manager, route_topic, vehicle_topic
    if affected_route is not None:
        db.refresh(affected_route)
        tracking_manager.broadcast_from_sync({
            "type": "route_update", "event": "route.pickup.cancelled",
            "route_id": str(affected_route.id),
            "vehicle_id": str(affected_route.vehicle_id),
            "pickup_id": str(pickup.id),
            "route_status": affected_route.status.value,
            "destination_state": affected_route.destination_state,
            "version": affected_route.version,
        }, {route_topic(affected_route.id), vehicle_topic(affected_route.vehicle_id)})
    return pickup_to_response(pickup, db)


@router.post("/{pickup_id}/assign", response_model=PickupRequestResponse)
def retry_assignment(
    pickup_id: UUID,
    current_user: User = Depends(require_hospital),
    db: Session = Depends(get_db),
):
    try:
        pickup = PickupService(db).retry_assignment(user_id=current_user.id, pickup_id=pickup_id)
    except HospitalProfileRequiredError:
        raise _profile_required()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except PickupNotFoundError:
        raise _not_found()
    except PickupNotAssignableError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This pickup is already assigned or no longer pending.",
        )
    return pickup_to_response(pickup, db)


@router.post("/{pickup_id}/collect", response_model=PickupRequestResponse)
def collect_pickup(
    pickup_id: UUID,
    payload: HandoverRequest,
    current_user: User = Depends(require_collector),
    db: Session = Depends(get_db),
):
    try:
        pickup = PickupService(db).collect_pickup(
            collector_id=current_user.id, pickup_id=pickup_id,
            token=payload.handover_qr, actual_weight_kg=payload.actual_weight_kg,
            packaging_condition=payload.packaging_condition,
            exception_reason=payload.exception_reason,
        )
    except PickupNotFoundError:
        raise _not_found()
    except NotAssignedCollectorError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This pickup isn't assigned to you.",
        )
    except PickupWeightValidationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except PickupNotCollectableError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This pickup isn't in a collectible state.",
        )
    return pickup_to_response(pickup, db)


@router.post("/{pickup_id}/start-transit", response_model=PickupRequestResponse)
def start_transit(
    pickup_id: UUID,
    current_user: User = Depends(require_collector),
    db: Session = Depends(get_db),
):
    try:
        pickup = PickupService(db).start_transit(
            collector_id=current_user.id, pickup_id=pickup_id
        )
    except PickupNotFoundError:
        raise _not_found()
    except NotAssignedCollectorError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This pickup isn't assigned to you.",
        )
    except PickupNotInTransitableError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This pickup must be collected before it can start transit.",
        )
    return pickup_to_response(pickup, db)