import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.config import get_settings
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.hospital_profile import HospitalProfile
from app.models.pickup_request import PickupRequest
from app.models.route import Route, RouteStatus
from app.models.user import User
from app.models.business import OrganizationMember
from app.models.vehicle import Vehicle
from app.schemas.route import RouteOptimizeRequest, RouteResponse
from app.realtime.tracking_manager import route_topic, tracking_manager, vehicle_topic
from app.services.route_optimization_service import (
    RouteForbiddenError,
    RouteOptimizationService,
    RouteValidationError,
    Point,
)

router = APIRouter(prefix="/routes", tags=["routes"])
require_route_operator = require_roles(UserRole.COLLECTOR, UserRole.ADMIN)


def _response(route, db: Session) -> RouteResponse:
    service = RouteOptimizationService(db, get_settings())
    return RouteResponse(
        id=route.id,
        vehicle_id=route.vehicle_id,
        tracking_session_id=route.tracking_session_id,
        version=route.version,
        status=route.status,
        destination_state=route.destination_state,
        destination_arrived_at=route.destination_arrived_at,
        destination_received_at=route.destination_received_at,
        completed_at=route.completed_at,
        is_optimized=route.is_optimized,
        total_distance_km=route.total_distance_km,
        estimated_duration_minutes=route.estimated_duration_minutes,
        origin_latitude=route.origin_latitude,
        origin_longitude=route.origin_longitude,
        destination_latitude=route.destination_latitude,
        destination_longitude=route.destination_longitude,
        change_reason=route.change_reason,
        routing_provider=route.routing_provider,
        geometry=route.geometry,
        optimization_details=route.optimization_details,
        created_at=route.created_at,
        updated_at=route.updated_at,
        stops=service.routes.list_stops(route.id),
    )


@router.post("/optimize", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
def optimize_route(
    payload: RouteOptimizeRequest,
    current_user: User = Depends(require_route_operator),
    db: Session = Depends(get_db),
):
    explicit = {
        item.pickup_id: Point(float(item.latitude), float(item.longitude))
        for item in payload.stop_coordinates
    }
    if set(explicit) - set(payload.pickup_ids):
        raise HTTPException(status_code=422, detail="stop_coordinates contains an unknown pickup_id.")
    try:
        route = RouteOptimizationService(db, get_settings()).optimize(
            user=current_user,
            vehicle_id=payload.vehicle_id,
            pickup_ids=payload.pickup_ids,
            origin_latitude=payload.origin_latitude,
            origin_longitude=payload.origin_longitude,
            stop_coordinates=explicit,
            destination_latitude=payload.destination_latitude,
            destination_longitude=payload.destination_longitude,
            start_at=payload.start_at,
            change_reason=payload.change_reason,
        )
        response = _response(route, db)
        tracking_manager.broadcast_from_sync({"type": "route_update", "event": "route.recalculated", "route_id": str(route.id), "vehicle_id": str(route.vehicle_id), "version": route.version}, {route_topic(route.id), vehicle_topic(route.vehicle_id)})
        return response
    except RouteForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except RouteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))




@router.post("/{route_id}/recalculate", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
def recalculate_route(
    route_id: uuid.UUID,
    current_user: User = Depends(require_route_operator),
    db: Session = Depends(get_db),
):
    service = RouteOptimizationService(db, get_settings())
    old = service.routes.get_by_id(route_id)
    if old is None:
        raise HTTPException(status_code=404, detail="Route not found.")
    vehicle = service.vehicles.get_by_id(old.vehicle_id)
    if vehicle is None or not service._can_manage(current_user, vehicle):
        raise HTTPException(status_code=403, detail="You are not authorized to recalculate this route.")
    if old.status not in {RouteStatus.DRAFT, RouteStatus.READY, RouteStatus.ACTIVE}:
        raise HTTPException(status_code=422, detail="Only draft, ready or active routes can be recalculated.")
    stops = service.routes.list_stops(old.id)
    if not stops:
        raise HTTPException(status_code=422, detail="Cannot recalculate a route with no pickup stops.")
    try:
        if old.status == RouteStatus.ACTIVE:
            route = service.recalculate_active(user=current_user, route_id=old.id,
                reason="Dispatcher requested live route recalculation")
        else:
            pickups = service._get_pickups(vehicle, [stop.pickup_id for stop in stops])
            # Previously this endpoint sent old saved coordinates as if they
            # were user-supplied constraints, rejecting updated authoritative
            # hospital/facility locations. Legacy hospital stops may use a
            # development-only fallback; facility destinations never do.
            explicit = {}
            for stop, pickup in zip(stops, pickups):
                hospital = db.get(HospitalProfile, pickup.hospital_id)
                if hospital is None or hospital.latitude is None or hospital.longitude is None:
                    explicit[stop.pickup_id] = Point(float(stop.latitude), float(stop.longitude))
            route = service.optimize(
                user=current_user, vehicle_id=old.vehicle_id,
                pickup_ids=[stop.pickup_id for stop in stops],
                origin_latitude=None, origin_longitude=None, stop_coordinates=explicit,
                destination_latitude=None, destination_longitude=None,
                change_reason="Route recalculated from the existing route.",
                force_recalculate=True,
            )
        response = _response(route, db)
        tracking_manager.broadcast_from_sync({"type": "route_update", "event": "route.updated", "route_id": str(route.id), "vehicle_id": str(route.vehicle_id), "version": route.version}, {route_topic(route.id), vehicle_topic(route.vehicle_id)})
        return response
    except RouteForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except RouteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{route_id}/confirm", response_model=RouteResponse)
def confirm_route(
    route_id: uuid.UUID,
    current_user: User = Depends(require_route_operator),
    db: Session = Depends(get_db),
):
    service = RouteOptimizationService(db, get_settings())
    try:
        route = service.confirm(user=current_user, route_id=route_id)
        response = _response(route, db)
        tracking_manager.broadcast_from_sync(
            {"type": "route_update", "event": "route.confirmed", "route_id": str(route.id), "vehicle_id": str(route.vehicle_id)},
            {route_topic(route.id), vehicle_topic(route.vehicle_id)},
        )
        return response
    except RouteForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except RouteValidationError as exc:
        raise HTTPException(status_code=404 if str(exc) == "Route not found." else 422, detail=str(exc))


@router.post("/{route_id}/start", response_model=RouteResponse)
def start_route(
    route_id: uuid.UUID,
    current_user: User = Depends(require_route_operator),
    db: Session = Depends(get_db),
):
    service = RouteOptimizationService(db, get_settings())
    try:
        route = service.start(user=current_user, route_id=route_id)
        response = _response(route, db)
        tracking_manager.broadcast_from_sync(
            {"type": "route_update", "event": "route.started", "route_id": str(route.id), "vehicle_id": str(route.vehicle_id), "tracking_session_id": str(route.tracking_session_id) if route.tracking_session_id else None},
            {route_topic(route.id), vehicle_topic(route.vehicle_id)},
        )
        return response
    except RouteForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except RouteValidationError as exc:
        raise HTTPException(status_code=404 if str(exc) == "Route not found." else 422, detail=str(exc))


@router.post("/{route_id}/stops/{stop_id}/complete", response_model=RouteResponse)
def complete_route_stop(
    route_id: uuid.UUID,
    stop_id: uuid.UUID,
    current_user: User = Depends(require_route_operator),
    db: Session = Depends(get_db),
):
    service = RouteOptimizationService(db, get_settings())
    try:
        route = service.complete_stop(user=current_user, route_id=route_id, stop_id=stop_id)
        response = _response(route, db)
        tracking_manager.broadcast_from_sync(
            {"type": "route_update", "event": "route.stop.updated", "route_id": str(route.id), "vehicle_id": str(route.vehicle_id), "status": route.status.value},
            {route_topic(route.id), vehicle_topic(route.vehicle_id)},
        )
        return response
    except RouteForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except RouteValidationError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 422, detail=str(exc))


@router.get("/ready", response_model=list[RouteResponse])
def ready_routes(
    current_user: User = Depends(require_route_operator),
    db: Session = Depends(get_db),
):
    """Return pending DRAFT and confirmed READY routes for authorized operators."""
    stmt = (
        select(Route)
        .join(Vehicle, Vehicle.id == Route.vehicle_id)
        .where(Route.status.in_([RouteStatus.DRAFT, RouteStatus.READY]), Vehicle.is_active.is_(True))
        .order_by(Route.updated_at.desc(), Route.version.desc())
    )
    if current_user.role == UserRole.COLLECTOR:
        org_ids = select(OrganizationMember.organization_id).where(
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.active.is_(True),
            OrganizationMember.member_role.in_(['owner', 'manager', 'dispatcher']))
        driver_org_ids = select(OrganizationMember.organization_id).where(
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.active.is_(True), OrganizationMember.member_role == 'driver')
        stmt = stmt.where((Vehicle.assigned_collector_id == current_user.id) &
                          ((Vehicle.organization_id.is_(None)) | (Vehicle.organization_id.in_(driver_org_ids))) |
                          (Vehicle.organization_id.in_(org_ids)))
        from app.services.organization_context import selected_org_id
        if selected_org_id() is not None:
            stmt = stmt.where(Vehicle.organization_id == selected_org_id())
    routes = list(db.execute(stmt).scalars().all())
    return [_response(route, db) for route in routes]


@router.get("/{route_id}", response_model=RouteResponse)
def get_route(
    route_id: uuid.UUID,
    current_user: User = Depends(require_route_operator),
    db: Session = Depends(get_db),
):
    service = RouteOptimizationService(db, get_settings())
    route = service.routes.get_by_id(route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found.")
    vehicle = service.vehicles.get_by_id(route.vehicle_id)
    if vehicle is None or not service._can_manage(current_user, vehicle):
        raise HTTPException(status_code=403, detail="You are not authorized to view this route.")
    return _response(route, db)


@router.get("/vehicles/{vehicle_id}/history", response_model=list[RouteResponse])
def route_history(
    vehicle_id: uuid.UUID,
    current_user: User = Depends(require_route_operator),
    db: Session = Depends(get_db),
):
    service = RouteOptimizationService(db, get_settings())
    vehicle = service.vehicles.get_by_id(vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    if not service._can_manage(current_user, vehicle):
        raise HTTPException(status_code=403, detail="You are not authorized to view this vehicle's route history.")
    return [_response(route, db) for route in service.routes.list_for_vehicle(vehicle_id)]
