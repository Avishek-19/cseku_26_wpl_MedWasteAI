"""Transaction-local reconciliation when an uncollected active-route stop is cancelled.

No commits or network broadcasts here. The caller owns the transaction and
publishes an update only *after* that transaction commits successfully.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pickup_request import PickupRequest
from app.models.route import Route, RouteStatus, RouteStop, RouteStopStatus, RouteDestinationState
from app.models.tracking import TrackingSession, TrackingSessionStatus, TrackingLocation, LocationSource
from app.models.vehicle import Vehicle
from app.models.waste_enums import PickupStatus, VehicleStatus
from app.services.route_optimization_service import HaversineRoutingProvider, Point

_TERMINAL = {RouteStopStatus.COLLECTED, RouteStopStatus.SKIPPED, RouteStopStatus.CANCELLED}


def reconcile_cancelled_stop(
    db: Session, *, route: Route, cancelled_stop: RouteStop,
    vehicle: Vehicle, pickup: PickupRequest, timestamp: datetime,
) -> str:
    """Cancel this stop, advance live progress and recompute a safe fallback path.

    Returns either 'continue', 'facility', or 'empty_route'. Existing collected
    waste must always reach the facility; empty routes must not drive there.
    """
    if route.status != RouteStatus.ACTIVE or cancelled_stop.status not in {
        RouteStopStatus.PENDING, RouteStopStatus.EN_ROUTE, RouteStopStatus.ARRIVED,
    }:
        raise ValueError("Only an uncollected stop on an active route can be cancelled")
    if cancelled_stop.pickup_id != pickup.id or route.vehicle_id != vehicle.id:
        raise ValueError("Cancellation stop does not belong to this pickup/vehicle")

    cancelled_stop.status = RouteStopStatus.CANCELLED
    cancelled_stop.completed_at = cancelled_stop.completed_at or timestamp
    stops = list(db.scalars(select(RouteStop).where(
        RouteStop.route_id == route.id).order_by(RouteStop.sequence).with_for_update(of=RouteStop)
    ).all())
    outstanding = [s for s in stops if s.status not in _TERMINAL]
    collected = any(s.status == RouteStopStatus.COLLECTED for s in stops)

    # Do not override an already-ARRIVED/EN_ROUTE stop. Promote a pending stop
    # only when we just cancelled the previously active one.
    if outstanding and not any(s.status in {RouteStopStatus.EN_ROUTE, RouteStopStatus.ARRIVED} for s in outstanding):
        outstanding[0].status = RouteStopStatus.EN_ROUTE

    outcome = 'continue' if outstanding else ('facility' if collected else 'empty_route')
    if outcome == 'facility':
        route.destination_state = RouteDestinationState.EN_ROUTE_TO_DESTINATION.value
    elif outcome == 'empty_route':
        route.status = RouteStatus.CANCELLED
        # This trip has no physical waste to deliver. End its GPS session and
        # only free the vehicle when there are no other reserved assignments.
        if route.tracking_session_id:
            session = db.get(TrackingSession, route.tracking_session_id)
            if session is not None and session.current_route_id == route.id:
                session.status = TrackingSessionStatus.CANCELLED
                session.ended_at = timestamp
                session.current_route_id = None
        waiting_job = db.scalar(select(PickupRequest.id).where(
            PickupRequest.assigned_vehicle_id == vehicle.id,
            PickupRequest.id != pickup.id,
            PickupRequest.status == PickupStatus.ASSIGNED,
        ).limit(1))
        vehicle.status = VehicleStatus.RESERVED if waiting_job is not None else VehicleStatus.AVAILABLE
    else:
        route.destination_state = RouteDestinationState.COLLECTION.value

    # A saved OSRM polyline/ETA is no longer valid once a stop is removed.
    # Use an explicitly marked *straight-line estimate* until a dispatcher
    # requests an authoritative OSRM replan; never retain cancelled waypoints.
    remaining_points = outstanding if outcome == 'continue' else []
    current_position = None
    if route.tracking_session_id:
        last = db.scalar(select(TrackingLocation).where(
            TrackingLocation.tracking_session_id == route.tracking_session_id,
            # Only device-authenticated, accepted telemetry may reposition a live
            # route. Browser-only or forged `source` labels remain map-only.
            TrackingLocation.provenance_verified.is_(True),
            TrackingLocation.anomaly_type.is_(None),
            TrackingLocation.accuracy_m.is_not(None),
            TrackingLocation.accuracy_m <= 100,
            TrackingLocation.source.in_([LocationSource.GPS_DEVICE, LocationSource.MOBILE_APP]),
        ).order_by(TrackingLocation.timestamp.desc()).limit(1))
        if last is not None:
            recorded = last.timestamp
            recorded = recorded.replace(tzinfo=timezone.utc) if recorded.tzinfo is None else recorded.astimezone(timezone.utc)
            if timedelta(0) <= timestamp - recorded <= timedelta(minutes=5):
                current_position = Point(float(last.latitude), float(last.longitude))
    if current_position is None:
        done = [s for s in stops if s.status == RouteStopStatus.COLLECTED]
        if done:
            last_done = done[-1]
            current_position = Point(float(last_done.latitude), float(last_done.longitude))
        elif route.origin_latitude is not None and route.origin_longitude is not None:
            current_position = Point(float(route.origin_latitude), float(route.origin_longitude))
    if current_position is None:
        current_position = Point(float(cancelled_stop.latitude), float(cancelled_stop.longitude))

    points = [current_position] + [Point(float(s.latitude), float(s.longitude)) for s in remaining_points]
    if outcome != 'empty_route' and route.destination_latitude is not None and route.destination_longitude is not None:
        points.append(Point(float(route.destination_latitude), float(route.destination_longitude)))
    speed = 30.0  # conservative *estimate*, never represented as OSRM road routing
    provider = HaversineRoutingProvider(speed)
    distance, duration, _ = provider.route(points)
    elapsed = timestamp
    current = points[0]
    late_ids: list[str] = []
    for stop in remaining_points:
        point = Point(float(stop.latitude), float(stop.longitude))
        # Preserve confirmed arrival evidence for another stop. A hospital
        # cancelling a different job must not rewrite its GPS arrival time.
        if stop.status != RouteStopStatus.ARRIVED:
            elapsed += timedelta(minutes=math.ceil(provider.distance(current, point) / speed * 60))
        next_pickup = db.get(PickupRequest, stop.pickup_id)
        if next_pickup and next_pickup.requested_pickup_at is not None:
            earliest = next_pickup.requested_pickup_at
            earliest = earliest.replace(tzinfo=timezone.utc) if earliest.tzinfo is None else earliest.astimezone(timezone.utc)
            elapsed = max(elapsed, earliest)
        if stop.status != RouteStopStatus.ARRIVED:
            stop.estimated_arrival_at = elapsed
        if next_pickup and next_pickup.requested_pickup_end_at is not None:
            deadline = next_pickup.requested_pickup_end_at
            deadline = deadline.replace(tzinfo=timezone.utc) if deadline.tzinfo is None else deadline.astimezone(timezone.utc)
            if elapsed > deadline:
                late_ids.append(str(stop.pickup_id))
        current = point
    # Include hospital waiting time in the estimated journey length.
    if len(points) >= 2 and remaining_points and outcome != 'empty_route':
        # Waiting time plus travel to the facility are both included.
        facility_leg_minutes = (math.ceil(provider.distance(points[-2], points[-1]) / speed * 60)
                                if len(points) == len(remaining_points) + 2 else 0)
        duration = math.ceil((elapsed + timedelta(minutes=facility_leg_minutes) - timestamp).total_seconds() / 60)
    route.geometry = None  # NEVER retain a stale OSRM road polyline
    # Existing route summary cards show the remaining journey, not the old
    # plan's length. Preserve the original summary in the audit metadata.
    old = dict(route.optimization_details or {})
    old.setdefault('pre_cancellation_distance_km',
                   float(route.total_distance_km) if route.total_distance_km is not None else None)
    old.setdefault('pre_cancellation_duration_minutes', route.estimated_duration_minutes)
    route.total_distance_km = Decimal(str(round(distance, 2)))
    route.estimated_duration_minutes = duration
    route.origin_latitude = Decimal(str(round(current_position.latitude, 6)))
    route.origin_longitude = Decimal(str(round(current_position.longitude, 6)))
    route.routing_provider = 'haversine'  # clearly an approximate fallback
    history = list(old.get('pickup_cancellations', []))
    history.append({'pickup_id': str(pickup.id), 'stop_id': str(cancelled_stop.id),
                    'at': timestamp.isoformat(), 'outcome': outcome})
    old.update({
        'pickup_cancellations': history,
        'remaining_stop_count': len(outstanding),
        'remaining_distance_km': round(distance, 2),
        'remaining_duration_minutes': duration,
        'route_geometry_stale': True,
        'route_replan_required': bool(remaining_points),
        'deadline_at_risk_pickup_ids': late_ids,
    })
    route.optimization_details = old
    route.change_reason = f'Pickup {pickup.id} cancelled during active dispatch; {outcome}.'
    return outcome
