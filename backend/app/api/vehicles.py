from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.models.business import OrganizationMember
from app.services.organization_context import selected_org_id
from app.models.vehicle import Vehicle
from app.schemas.vehicle import VehicleCreate, VehicleResponse, VehicleUpdate
from app.services.vehicle_service import (
    VehicleCodeAlreadyExistsError,
    VehicleNotFoundError,
    VehicleConflictError,
    VehicleService,
)

router = APIRouter(prefix="/vehicles", tags=["vehicles"])

require_collector = require_roles(UserRole.COLLECTOR)
require_operations = require_roles(UserRole.COLLECTOR, UserRole.ADMIN)


@router.post("", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
def create_vehicle(
    payload: VehicleCreate,
    current_user: User = Depends(require_collector),
    db: Session = Depends(get_db),
):
    try:
        return VehicleService(db).create_vehicle(collector_id=current_user.id, data=payload)
    except VehicleCodeAlreadyExistsError:
        raise HTTPException(status_code=409, detail="A vehicle with this code already exists.")
    except VehicleConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/mine", response_model=list[VehicleResponse])
def list_my_vehicles(
    current_user: User = Depends(require_collector), db: Session = Depends(get_db)
):
    return VehicleService(db).list_my_vehicles(current_user.id)



@router.get("/operations", response_model=list[VehicleResponse])
def list_operation_vehicles(
    current_user: User = Depends(require_operations), db: Session = Depends(get_db)
):
    stmt = select(Vehicle).where(Vehicle.is_active.is_(True))
    if current_user.role == UserRole.COLLECTOR:
        membership = select(OrganizationMember.organization_id).where(
            OrganizationMember.user_id == current_user.id, OrganizationMember.active.is_(True))
        stmt = stmt.where((Vehicle.organization_id.in_(membership)) |
                          ((Vehicle.assigned_collector_id == current_user.id) & Vehicle.organization_id.is_(None)))
        if selected_org_id() is not None:
            stmt = stmt.where(Vehicle.organization_id == selected_org_id())
    return list(db.execute(stmt.order_by(Vehicle.vehicle_code)).scalars().all())

@router.patch("/{vehicle_id}", response_model=VehicleResponse)
def update_vehicle(
    vehicle_id: UUID,
    payload: VehicleUpdate,
    current_user: User = Depends(require_collector),
    db: Session = Depends(get_db),
):
    try:
        return VehicleService(db).update_vehicle(
            collector_id=current_user.id, vehicle_id=vehicle_id, data=payload
        )
    except VehicleNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found.")
    except VehicleConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
