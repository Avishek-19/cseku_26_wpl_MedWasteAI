import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.models.business import Organization, OrganizationMember
from app.models.pickup_request import PickupRequest
from app.models.route import Route, RouteStatus
from app.models.waste_enums import PickupStatus, VehicleStatus
from app.services.organization_eligibility import eligible_member_organizations
from app.services.organization_context import selected_org_id

from app.models.vehicle import Vehicle
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.vehicle import VehicleCreate, VehicleUpdate


class VehicleCodeAlreadyExistsError(Exception):
    pass


class VehicleNotFoundError(Exception):
    pass


class VehicleConflictError(Exception):
    pass


class VehicleService:
    def __init__(self, db: Session):
        self.db = db
        self.vehicles = VehicleRepository(db)

    def _validate_driver(self, organization_id: uuid.UUID, driver_id: uuid.UUID) -> None:
        from app.models.user import User
        from app.models.roles import UserRole
        candidate = self.db.get(User, driver_id)
        membership = self.db.scalar(select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == driver_id,
            OrganizationMember.active.is_(True)).limit(1))
        if (not candidate or not candidate.is_active or candidate.role != UserRole.COLLECTOR
                or not membership or membership.member_role not in {'owner', 'manager', 'driver'}):
            raise VehicleConflictError("Select an active owner, manager or driver from this collection company.")

    def create_vehicle(self, *, collector_id: uuid.UUID, data: VehicleCreate) -> Vehicle:
        if self.vehicles.get_by_code(data.vehicle_code):
            raise VehicleCodeAlreadyExistsError()
        companies = eligible_member_organizations(self.db, collector_id, "COLLECTION_COMPANY")
        company = next((c for c in companies if c.id == data.organization_id), None) if data.organization_id else (
            next((c for c in companies if c.id == selected_org_id()), None) if selected_org_id() else (
            companies[0] if len(companies) == 1 else None))
        if company is None:
            raise VehicleConflictError("Join/select a collection company before creating a vehicle.")
        member = self.db.scalar(select(OrganizationMember).where(
            OrganizationMember.organization_id == company.id,
            OrganizationMember.user_id == collector_id,
            OrganizationMember.active.is_(True)).limit(1))
        if not member or member.member_role not in {'owner', 'manager', 'dispatcher', 'driver'}:
            raise VehicleConflictError("Fleet registration requires authorized company operations membership.")
        if company.status != 'verified' and get_settings().environment.lower() not in {'development', 'test'}:
            raise VehicleConflictError("Company verification is required for commercial vehicles.")
        driver_id = data.assigned_collector_id or collector_id
        self._validate_driver(company.id, driver_id)
        vehicle = Vehicle(
            vehicle_code=data.vehicle_code,
            assigned_collector_id=driver_id,
            organization_id=company.id,
            capacity_kg=data.capacity_kg,
            location=data.location,
        )
        return self.vehicles.create(vehicle)

    def list_my_vehicles(self, collector_id: uuid.UUID) -> list[Vehicle]:
        org_ids = [o.id for o in eligible_member_organizations(self.db, collector_id, 'COLLECTION_COMPANY')]
        if selected_org_id() is not None:
            org_ids = [o for o in org_ids if o == selected_org_id()]
        return list(self.db.scalars(select(Vehicle).where(
            ((Vehicle.assigned_collector_id == collector_id) & Vehicle.organization_id.is_(None)) |
            (Vehicle.organization_id.in_(org_ids))
        ).order_by(Vehicle.vehicle_code)).all())

    def update_vehicle(
        self, *, collector_id: uuid.UUID, vehicle_id: uuid.UUID, data: VehicleUpdate
    ) -> Vehicle:
        vehicle = self.vehicles.get_by_id(vehicle_id)
        if vehicle is None:
            raise VehicleNotFoundError()
        if vehicle.organization_id is not None:
            member = self.db.scalar(select(OrganizationMember).where(
                OrganizationMember.organization_id == vehicle.organization_id,
                OrganizationMember.user_id == collector_id,
                OrganizationMember.active.is_(True),
                OrganizationMember.member_role.in_(['owner', 'manager', 'dispatcher'])).limit(1))
            if member is None:
                raise VehicleNotFoundError()
        elif vehicle.assigned_collector_id != collector_id:
            raise VehicleNotFoundError()

        # Explicit driver assignment is only safe before reservation. Changing
        # drivers during a job would orphan pickup proofs, GPS and route stops.
        if data.assigned_collector_id is not None and data.assigned_collector_id != vehicle.assigned_collector_id:
            if vehicle.organization_id is None:
                raise VehicleConflictError("Legacy unlinked vehicles cannot be reassigned.")
            if vehicle.status != VehicleStatus.AVAILABLE or not vehicle.is_active:
                raise VehicleConflictError("Driver can change only while the vehicle is active and AVAILABLE.")
            active_job = self.db.scalar(select(PickupRequest.id).where(
                PickupRequest.assigned_vehicle_id == vehicle.id,
                PickupRequest.status.in_([PickupStatus.ASSIGNED, PickupStatus.COLLECTED, PickupStatus.IN_TRANSIT])
            ).limit(1))
            pending_route = self.db.scalar(select(Route.id).where(
                Route.vehicle_id == vehicle.id,
                Route.status.in_([RouteStatus.DRAFT, RouteStatus.READY, RouteStatus.ACTIVE])
            ).limit(1))
            if active_job or pending_route:
                raise VehicleConflictError("Vehicle has scheduled work; complete or cancel it before changing drivers.")
            self._validate_driver(vehicle.organization_id, data.assigned_collector_id)
            vehicle.assigned_collector_id = data.assigned_collector_id
        # Status changes are allowed only from route/maintenance workflows.
        # PATCH cannot turn an in-flight or reserved vehicle into AVAILABLE.
        if data.is_active is False:
            active_jobs = self.db.scalar(select(PickupRequest.id).where(
                PickupRequest.assigned_vehicle_id == vehicle.id,
                PickupRequest.status.in_([PickupStatus.ASSIGNED, PickupStatus.COLLECTED, PickupStatus.IN_TRANSIT])
            ).limit(1))
            active_routes = self.db.scalar(select(Route.id).where(
                Route.vehicle_id == vehicle.id, Route.status.in_([RouteStatus.DRAFT, RouteStatus.READY, RouteStatus.ACTIVE])
            ).limit(1))
            if active_jobs or active_routes or vehicle.status != VehicleStatus.AVAILABLE:
                raise VehicleConflictError("Cannot deactivate a vehicle with reserved/in-flight work.")
        if data.location is not None:
            vehicle.location = data.location
        if data.is_active is not None:
            vehicle.is_active = data.is_active

        return self.vehicles.update(vehicle)
