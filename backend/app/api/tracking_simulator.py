from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.config import get_settings
from app.core.db import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.services.gps_simulator_service import SimulatorError, get_simulator
from app.services.tracking_service import TrackingForbiddenError

router = APIRouter(prefix="/tracking/simulator", tags=["tracking-simulator"])
require_simulator_user = require_roles(UserRole.COLLECTOR, UserRole.ADMIN)


class SimulatorStartRequest(BaseModel):
    vehicle_id: uuid.UUID
    route_id: uuid.UUID
    speed_multiplier: float = Field(default=1.0, ge=0.25, le=20)


class SimulatorStateResponse(BaseModel):
    simulation_id: uuid.UUID
    vehicle_id: uuid.UUID
    route_id: uuid.UUID
    tracking_session_id: uuid.UUID
    speed_multiplier: float
    status: str
    progress: float


def _response(state) -> SimulatorStateResponse:
    return SimulatorStateResponse(
        simulation_id=state.simulation_id,
        vehicle_id=state.vehicle_id,
        route_id=state.route_id,
        tracking_session_id=state.tracking_session_id,
        speed_multiplier=state.speed_multiplier,
        status=state.status,
        progress=round(state.progress, 4),
    )


@router.post("/start", response_model=SimulatorStateResponse, status_code=status.HTTP_201_CREATED)
async def start_simulator(
    payload: SimulatorStartRequest,
    current_user: User = Depends(require_simulator_user),
):
    try:
        state = await get_simulator(get_settings()).start(
            user=current_user,
            vehicle_id=payload.vehicle_id,
            route_id=payload.route_id,
            speed_multiplier=payload.speed_multiplier,
        )
        return _response(state)
    except TrackingForbiddenError:
        raise HTTPException(status_code=403, detail="You are not authorized to simulate this vehicle.")
    except SimulatorError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{simulation_id}/pause", response_model=SimulatorStateResponse)
async def pause_simulator(
    simulation_id: uuid.UUID,
    current_user: User = Depends(require_simulator_user),
):
    try:
        state = await get_simulator(get_settings()).pause(simulation_id, current_user)
        return _response(state)
    except TrackingForbiddenError:
        raise HTTPException(status_code=403, detail="You are not authorized to control this simulation.")
    except SimulatorError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{simulation_id}/resume", response_model=SimulatorStateResponse)
async def resume_simulator(
    simulation_id: uuid.UUID,
    current_user: User = Depends(require_simulator_user),
):
    try:
        state = await get_simulator(get_settings()).resume(simulation_id, current_user)
        return _response(state)
    except TrackingForbiddenError:
        raise HTTPException(status_code=403, detail="You are not authorized to control this simulation.")
    except SimulatorError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{simulation_id}/reset", response_model=SimulatorStateResponse)
async def reset_simulator(
    simulation_id: uuid.UUID,
    current_user: User = Depends(require_simulator_user),
):
    try:
        state = await get_simulator(get_settings()).reset(simulation_id, current_user)
        return _response(state)
    except TrackingForbiddenError:
        raise HTTPException(status_code=403, detail="You are not authorized to control this simulation.")
    except SimulatorError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{simulation_id}", response_model=SimulatorStateResponse)
async def simulator_status(
    simulation_id: uuid.UUID,
    current_user: User = Depends(require_simulator_user),
):
    try:
        return _response(await get_simulator(get_settings()).status(simulation_id, current_user))
    except TrackingForbiddenError:
        raise HTTPException(status_code=403, detail="You are not authorized to control this simulation.")
    except SimulatorError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
