import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import select, or_

from app.api.deps import get_current_user, require_roles
from app.core.config import get_settings
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.models.tracking import TrackingSession, TrackingLocation
from app.models.route import Route, RouteStop, RouteStatus
from app.models.vehicle import Vehicle
from app.models.pickup_request import PickupRequest, PickupRequestItem
from app.models.hospital_profile import HospitalProfile
from app.models.facility_profile import TreatmentFacilityProfile
from app.models.matching_record import MatchingRecord
from app.realtime.tracking_authorization import can_view_vehicle
from app.services.organization_eligibility import profile_for_user
from app.schemas.tracking import GPSLocationCreate, TrackingLocationResponse, TrackingSessionCreate, TrackingSessionResponse
from app.services.gps_validation_service import GPSValidationError
from app.services.gps_device_provenance import GPSProvenanceError, verify_gps_signature
from app.realtime.tracking_manager import route_topic, tracking_manager, vehicle_topic
from app.services.tracking_service import (
    ActiveTrackingSessionExistsError,
    ActiveRouteInProgressError,
    TrackingSessionAlreadyClosedError,
    TrackingForbiddenError,
    TrackingNotFoundError,
    TrackingService,
)

router = APIRouter(prefix="/tracking", tags=["tracking"])
require_tracking_operator = require_roles(UserRole.COLLECTOR, UserRole.ADMIN)


@router.post("/sessions", response_model=TrackingSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_tracking_session(
    payload: TrackingSessionCreate,
    current_user: User = Depends(require_tracking_operator),
    db: Session = Depends(get_db),
):
    try:
        session = TrackingService(db, get_settings()).create_session(user=current_user, data=payload)
        await tracking_manager.broadcast({"type": "status_update", "event": "tracking.session.started", "vehicle_id": str(session.vehicle_id), "tracking_session_id": str(session.id), "status": session.status.value}, {vehicle_topic(session.vehicle_id)})
        return session
    except ActiveTrackingSessionExistsError:
        raise HTTPException(status_code=409, detail="An active tracking session already exists for this vehicle.")
    except TrackingNotFoundError:
        raise HTTPException(status_code=404, detail="Vehicle or pickup not found.")
    except TrackingForbiddenError:
        raise HTTPException(status_code=403, detail="You are not authorized to track this vehicle.")


@router.post("/sessions/{session_id}/locations", response_model=TrackingLocationResponse, status_code=status.HTTP_201_CREATED)
async def record_location(
    session_id: uuid.UUID,
    payload: GPSLocationCreate,
    request: Request,
    current_user: User = Depends(require_tracking_operator),
    db: Session = Depends(get_db),
):
    try:
        # Never treat the user-controlled `source` field as device identity.
        # Unenrolled reports remain map-only; signed reports can drive geofence
        # progress once all physics checks pass.
        headers = request.headers
        signature_headers = [headers.get(x) for x in (
            'X-GPS-Device-ID', 'X-GPS-Nonce', 'X-GPS-Sent-At', 'X-GPS-Signature')]
        verified = None
        if any(item is not None for item in signature_headers):
            if not all(item is not None for item in signature_headers):
                raise GPSProvenanceError('All GPS signature headers are required.')
            session = db.get(TrackingSession, session_id)
            if session is None:
                raise TrackingNotFoundError()
            verified = verify_gps_signature(get_settings(), session_id=session_id,
                vehicle_id=session.vehicle_id, payload=payload,
                device_id=signature_headers[0], nonce=signature_headers[1],
                sent_at=signature_headers[2], signature=signature_headers[3])
        location = TrackingService(db, get_settings()).record_location(
            user=current_user, session_id=session_id, data=payload, verified_device=verified)
        event = {"type": "location_update", "event": "vehicle.location.updated", "vehicle_id": str(location.vehicle_id), "tracking_session_id": str(location.tracking_session_id), "location": {"id": str(location.id), "latitude": float(location.latitude), "longitude": float(location.longitude), "timestamp": location.timestamp.isoformat(), "speed_kmh": float(location.speed_kmh) if location.speed_kmh is not None else None, "heading_degrees": float(location.heading_degrees) if location.heading_degrees is not None else None, "accuracy_m": float(location.accuracy_m) if location.accuracy_m is not None else None, "altitude_m": float(location.altitude_m) if location.altitude_m is not None else None, "source": location.source.value, "provenance_verified": location.provenance_verified, "anomaly_type": location.anomaly_type.value if location.anomaly_type else None}}
        topics = {vehicle_topic(location.vehicle_id)}
        session = db.get(TrackingSession, location.tracking_session_id)
        session_route_id = session.current_route_id if session else None
        if session_route_id:
            topics.add(route_topic(session_route_id))
            event["route_progress"] = TrackingService(db, get_settings()).get_route_progress(session_route_id)
        await tracking_manager.broadcast(event, topics)
        return location
    except TrackingNotFoundError:
        raise HTTPException(status_code=404, detail="Tracking session not found.")
    except TrackingForbiddenError:
        raise HTTPException(status_code=403, detail="You are not authorized to update this tracking session.")
    except GPSProvenanceError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except GPSValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/vehicles/{vehicle_id}/latest", response_model=TrackingLocationResponse | None)
def get_latest_location(
    vehicle_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return TrackingService(db, get_settings()).get_latest_location(user=current_user, vehicle_id=vehicle_id)
    except TrackingNotFoundError:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    except TrackingForbiddenError:
        raise HTTPException(status_code=403, detail="You are not authorized to view this vehicle's location.")


@router.post("/sessions/{session_id}/complete", response_model=TrackingSessionResponse)
async def complete_tracking_session(
    session_id: uuid.UUID,
    current_user: User = Depends(require_tracking_operator),
    db: Session = Depends(get_db),
):
    try:
        session = TrackingService(db, get_settings()).complete_session(user=current_user, session_id=session_id)
        await tracking_manager.broadcast({"type": "status_update", "event": "tracking.session.completed", "vehicle_id": str(session.vehicle_id), "tracking_session_id": str(session.id), "status": session.status.value}, {vehicle_topic(session.vehicle_id)})
        return session
    except ActiveRouteInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TrackingSessionAlreadyClosedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TrackingNotFoundError:
        raise HTTPException(status_code=404, detail="Tracking session not found.")
    except TrackingForbiddenError:
        raise HTTPException(status_code=403, detail="You are not authorized to complete this tracking session.")


@router.get("/role-overview")
def role_tracking_overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return only vehicles/routes the authenticated role is entitled to see.

    This endpoint is intentionally role-scoped; the client never receives an
    unrestricted fleet feed and cannot widen its scope by changing a query id.
    """
    from app.realtime.tracking_authorization import can_view_vehicle
    vehicles = list(db.scalars(select(Vehicle).where(Vehicle.is_active.is_(True))).all())
    vehicles = [v for v in vehicles if can_view_vehicle(db, current_user, v.id)]
    result = []
    for vehicle in vehicles:
        route = db.scalar(select(Route).where(
            Route.vehicle_id == vehicle.id,
            Route.status == RouteStatus.ACTIVE
        ).order_by(Route.version.desc()))
        latest = db.scalar(select(TrackingLocation).where(
            TrackingLocation.vehicle_id == vehicle.id,
            TrackingLocation.tracking_session_id == route.tracking_session_id
        ).order_by(TrackingLocation.timestamp.desc()).limit(1)) if route and route.tracking_session_id else None
        stops = []
        if route:
            for stop in db.scalars(select(RouteStop).where(RouteStop.route_id == route.id).order_by(RouteStop.sequence)).all():
                pickup = db.get(PickupRequest, stop.pickup_id)
                if current_user.role == UserRole.HOSPITAL:
                    profile = profile_for_user(db, current_user.id, "HOSPITAL")
                    if not profile or not pickup or pickup.hospital_id != profile.id:
                        continue
                elif current_user.role == UserRole.FACILITY:
                    profile = profile_for_user(db, current_user.id, "TREATMENT_FACILITY")
                    if not profile or not pickup or not db.scalar(select(MatchingRecord.id).join(PickupRequestItem,
                        MatchingRecord.waste_record_id == PickupRequestItem.waste_record_id).where(
                        PickupRequestItem.pickup_request_id == pickup.id,
                        MatchingRecord.confirmed_facility_id == profile.id,
                        MatchingRecord.is_confirmed.is_(True)).limit(1)):
                        continue
                stops.append({
                    "id": str(stop.id), "pickup_id": str(stop.pickup_id),
                    "sequence": stop.sequence, "latitude": float(stop.latitude),
                    "longitude": float(stop.longitude), "status": stop.status.value,
                    "priority": pickup.priority.value if pickup else None,
                    "pickup_status": pickup.status.value if pickup else None,
                })
        result.append({
            "vehicle": {
                "id": str(vehicle.id), "vehicle_code": vehicle.vehicle_code,
                "status": vehicle.status.value, "capacity_kg": float(vehicle.capacity_kg),
                "assigned_collector_id": str(vehicle.assigned_collector_id),
            },
            "location": None if latest is None else {
                "latitude": float(latest.latitude), "longitude": float(latest.longitude),
                "speed_kmh": float(latest.speed_kmh) if latest.speed_kmh is not None else None,
                "heading_degrees": float(latest.heading_degrees) if latest.heading_degrees is not None else None,
                "timestamp": latest.timestamp.isoformat(),
                "source": latest.source.value,
                "provenance_verified": bool(latest.provenance_verified),
                "anomaly_type": latest.anomaly_type.value if latest.anomaly_type else None,
                "demo": latest.source.value == 'simulator',
                "stale": (datetime.now(timezone.utc) - (
                    latest.timestamp if latest.timestamp.tzinfo is not None
                    else latest.timestamp.replace(tzinfo=timezone.utc)
                )).total_seconds() > get_settings().gps_stale_threshold_seconds,
            },
            "route": None if route is None else {
                "id": str(route.id), "version": route.version, "status": route.status.value,
                "tracking_session_id": str(route.tracking_session_id) if route.tracking_session_id and current_user.role in {UserRole.COLLECTOR, UserRole.ADMIN} else None,
                "destination_state": route.destination_state,
                "destination_arrived_at": route.destination_arrived_at.isoformat() if route.destination_arrived_at else None,
                "destination_received_at": route.destination_received_at.isoformat() if route.destination_received_at else None,
                "completed_at": route.completed_at.isoformat() if route.completed_at else None,
                "geometry": route.geometry,
                "origin_latitude": float(route.origin_latitude) if route.origin_latitude is not None else None,
                "origin_longitude": float(route.origin_longitude) if route.origin_longitude is not None else None,
                "destination_latitude": float(route.destination_latitude) if route.destination_latitude is not None else None,
                "destination_longitude": float(route.destination_longitude) if route.destination_longitude is not None else None,
                "stops": stops,
            }
        })
    return {"role": current_user.role.value, "vehicles": result}
