"""Backend authorization for live tracking subscriptions."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.facility_profile import TreatmentFacilityProfile
from app.models.hospital_profile import HospitalProfile
from app.models.matching_record import MatchingRecord
from app.models.pickup_request import PickupRequest, PickupRequestItem
from app.models.roles import UserRole
from app.models.route import Route, RouteStop, RouteStatus
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.waste_enums import PickupStatus
from app.services.organization_eligibility import profile_for_user, can_profile_action
from app.models.business import OrganizationMember
from app.services.organization_context import selected_org_id


class TrackingSubscriptionForbidden(Exception):
    pass


def _hospital_can_view_vehicle(db: Session, user: User, vehicle_id: uuid.UUID) -> bool:
    profile = profile_for_user(db, user.id, "HOSPITAL")
    if profile is None or not can_profile_action(db, profile, user.id, "HOSPITAL", "tracking_read"):
        return False
    stmt = select(PickupRequest.id).where(
        PickupRequest.hospital_id == profile.id,
        PickupRequest.assigned_vehicle_id == vehicle_id,
        PickupRequest.status.in_([PickupStatus.ASSIGNED, PickupStatus.COLLECTED, PickupStatus.IN_TRANSIT]),
    ).limit(1)
    return db.execute(stmt).first() is not None


def _facility_can_view_vehicle(db: Session, user: User, vehicle_id: uuid.UUID) -> bool:
    profile = profile_for_user(db, user.id, "TREATMENT_FACILITY")
    if profile is None or not can_profile_action(db, profile, user.id, "TREATMENT_FACILITY", "tracking_read"):
        return False
    # A pickup is visible to the facility only when at least one waste record
    # in that pickup has a confirmed match to this facility.
    stmt = (
        select(PickupRequest.id)
        .join(PickupRequestItem, PickupRequestItem.pickup_request_id == PickupRequest.id)
        .join(MatchingRecord, MatchingRecord.waste_record_id == PickupRequestItem.waste_record_id)
        .where(
            PickupRequest.assigned_vehicle_id == vehicle_id,
            PickupRequest.status.in_([PickupStatus.ASSIGNED, PickupStatus.COLLECTED, PickupStatus.IN_TRANSIT]),
            MatchingRecord.confirmed_facility_id == profile.id,
            MatchingRecord.is_confirmed.is_(True),
        )
        .limit(1)
    )
    return db.execute(stmt).first() is not None


def _vehicle_has_exclusive_active_shipments(db: Session, user: User, vehicle_id: uuid.UUID) -> bool:
    """A vehicle topic contains unredacted GPS and route progress.

    Until per-shipment fanout exists, never expose shared hospital or multi-
    destination fleet feeds to unrelated clients. Admin and assigned driver
    have operational permission; hospitals/facilities only see exclusive trips.
    """
    routes = list(db.scalars(select(Route).where(
        Route.vehicle_id == vehicle_id, Route.status == RouteStatus.ACTIVE)).all())
    if not routes:
        return False
    # The topic publishes *all* stops including completed ones. Checking
    # merely today's unfinished pickups leaks a different hospital's prior
    # handover/location through the historical stops and raw route messages.
    active = list(db.scalars(select(PickupRequest).join(RouteStop,
        RouteStop.pickup_id == PickupRequest.id).where(
        RouteStop.route_id.in_([r.id for r in routes]))).all())
    if not active:
        return False
    if user.role == UserRole.HOSPITAL:
        profile = profile_for_user(db, user.id, "HOSPITAL")
        return bool(profile and can_profile_action(db, profile, user.id, "HOSPITAL", "tracking_read") and all(p.hospital_id == profile.id for p in active))
    if user.role == UserRole.FACILITY:
        profile = profile_for_user(db, user.id, "TREATMENT_FACILITY")
        if profile is None or not can_profile_action(db, profile, user.id, "TREATMENT_FACILITY", "tracking_read"):return False
        for pickup in active:
            matches = list(db.scalars(select(MatchingRecord).join(PickupRequestItem,
                PickupRequestItem.waste_record_id == MatchingRecord.waste_record_id).where(
                PickupRequestItem.pickup_request_id == pickup.id,
                MatchingRecord.is_confirmed.is_(True))).all())
            if not matches or any(m.confirmed_facility_id != profile.id for m in matches):
                return False
        return True
    return False


def can_view_vehicle(db: Session, user: User, vehicle_id: uuid.UUID) -> bool:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        return False
    if user.role == UserRole.ADMIN:
        return True
    if user.role == UserRole.COLLECTOR:
        if vehicle.organization_id is None:
            return selected_org_id() is None and vehicle.assigned_collector_id == user.id
        if selected_org_id() is not None and selected_org_id() != vehicle.organization_id:
            return False
        authorized = db.scalar(select(OrganizationMember.member_role).where(
            OrganizationMember.organization_id == vehicle.organization_id,
            OrganizationMember.user_id == user.id,
            OrganizationMember.active.is_(True)).limit(1))
        return authorized in {'owner', 'manager', 'dispatcher', 'driver'}
    if user.role == UserRole.HOSPITAL:
        return _hospital_can_view_vehicle(db, user, vehicle_id) and _vehicle_has_exclusive_active_shipments(db, user, vehicle_id)
    if user.role == UserRole.FACILITY:
        return _facility_can_view_vehicle(db, user, vehicle_id) and _vehicle_has_exclusive_active_shipments(db, user, vehicle_id)
    return False


def can_view_route(db: Session, user: User, route_id: uuid.UUID) -> bool:
    route = db.get(Route, route_id)
    if route is None:
        return False
    if user.role in (UserRole.ADMIN, UserRole.COLLECTOR):
        vehicle = db.get(Vehicle, route.vehicle_id)
        if vehicle is None:
            return False
        return can_view_vehicle(db, user, route.vehicle_id)
    if route.status != RouteStatus.ACTIVE:
        return False
    if not can_view_vehicle(db, user, route.vehicle_id):
        return False
    if user.role == UserRole.HOSPITAL:
        profile = profile_for_user(db, user.id, "HOSPITAL")
        return profile is not None and db.scalar(select(RouteStop.id).join(PickupRequest,
            RouteStop.pickup_id == PickupRequest.id).where(RouteStop.route_id == route.id,
            PickupRequest.hospital_id == profile.id, PickupRequest.status.in_(
                [PickupStatus.ASSIGNED, PickupStatus.COLLECTED, PickupStatus.IN_TRANSIT])).limit(1)) is not None
    if user.role == UserRole.FACILITY:
        profile = profile_for_user(db, user.id, "TREATMENT_FACILITY")
        return profile is not None and db.scalar(select(RouteStop.id).join(PickupRequest,
            RouteStop.pickup_id == PickupRequest.id).join(PickupRequestItem,
            PickupRequestItem.pickup_request_id == PickupRequest.id).join(MatchingRecord,
            MatchingRecord.waste_record_id == PickupRequestItem.waste_record_id).where(
            RouteStop.route_id == route.id, MatchingRecord.confirmed_facility_id == profile.id,
            MatchingRecord.is_confirmed.is_(True), PickupRequest.status.in_(
                [PickupStatus.ASSIGNED, PickupStatus.COLLECTED, PickupStatus.IN_TRANSIT])).limit(1)) is not None
    return False


def authorize_subscription(
    db: Session,
    user: User,
    *,
    vehicle_id: uuid.UUID | None = None,
    route_id: uuid.UUID | None = None,
) -> set[str]:
    if vehicle_id is None and route_id is None:
        raise TrackingSubscriptionForbidden("A vehicle_id or route_id subscription is required.")

    topics: set[str] = set()
    if vehicle_id is not None:
        if not can_view_vehicle(db, user, vehicle_id):
            raise TrackingSubscriptionForbidden("You are not authorized to view this vehicle.")
        topics.add(f"vehicle:{vehicle_id}")

    if route_id is not None:
        if not can_view_route(db, user, route_id):
            raise TrackingSubscriptionForbidden("You are not authorized to view this route.")
        topics.add(f"route:{route_id}")

    return topics
