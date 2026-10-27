from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import decode_access_token
from app.services.organization_context import select_organization, reset_organization
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.realtime.tracking_authorization import TrackingSubscriptionForbidden, authorize_subscription, can_view_vehicle, can_view_route
from app.realtime.tracking_manager import tracking_manager

router = APIRouter(tags=["tracking-realtime"])


def _authenticate(websocket: WebSocket, db: Session) -> User | None:
    settings = get_settings()
    token = websocket.cookies.get(settings.auth_cookie_name)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    user = UserRepository(db).get_by_id(user_id)
    return user if user is not None and user.is_active and payload.get("ver", 0) == user.auth_version else None


@router.websocket("/api/v1/tracking/ws")
async def tracking_websocket(websocket: WebSocket) -> None:
    settings = get_settings()
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.cors_origin_list:
        await websocket.close(code=1008, reason="Origin not allowed.")
        return
    if not settings.websocket_enabled:
        await websocket.close(code=1008, reason="Real-time tracking is disabled.")
        return

    try:
        context_token = select_organization(websocket.query_params.get('organization_id'))
    except ValueError:
        await websocket.close(code=1008, reason='Invalid organization identifier.')
        return
    db = SessionLocal(expire_on_commit=False)
    user = _authenticate(websocket, db)
    if user is None:
        db.close()
        reset_organization(context_token)
        await websocket.close(code=1008, reason="Authentication required.")
        return

    connected_auth_version = user.auth_version
    token_expiry = float(decode_access_token(websocket.cookies.get(settings.auth_cookie_name))["exp"])
    db.commit()  # Idle sockets must not retain a pooled database connection.
    await tracking_manager.connect(websocket)
    heartbeat_task: asyncio.Task | None = None
    subscribed_topics: set[str] = set()

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(settings.websocket_heartbeat_seconds)
            if datetime.now(timezone.utc).timestamp() >= token_expiry:
                await websocket.close(code=1008, reason="Session expired.")
                return
            db.expire_all()
            fresh_user = db.get(User, user.id)
            if fresh_user is None or not fresh_user.is_active or fresh_user.auth_version != connected_auth_version:
                await websocket.close(code=1008, reason="Access revoked.")
                return
            for topic in list(subscribed_topics):
                typ, identifier = topic.split(":", 1)
                allowed = can_view_vehicle(db, fresh_user, uuid.UUID(identifier)) if typ == "vehicle" else can_view_route(db, fresh_user, uuid.UUID(identifier))
                if not allowed:
                    await tracking_manager.unsubscribe(websocket, {topic})
                    subscribed_topics.discard(topic)
            db.commit()
            await tracking_manager.send(websocket, {"type": "ping", "timestamp": datetime.now(timezone.utc).isoformat()})

    try:
        await tracking_manager.send(
            websocket,
            {
                "type": "connected",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user_id": str(user.id),
                "role": user.role.value,
            },
        )
        heartbeat_task = asyncio.create_task(heartbeat())

        while True:
            try:
                message = await websocket.receive_json()
            except ValueError:
                await tracking_manager.send(websocket, {"type": "error", "code": "INVALID_JSON"})
                continue
            if not isinstance(message, dict):
                await tracking_manager.send(websocket, {"type": "error", "code": "INVALID_EVENT"})
                continue
            message_type = message.get("type")

            if message_type == "pong":
                continue

            if message_type == "ping":
                await tracking_manager.send(
                    websocket,
                    {"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()},
                )
                continue

            if message_type not in {"subscribe", "unsubscribe"}:
                await tracking_manager.send(websocket, {"type": "error", "code": "INVALID_EVENT", "message": "Unsupported event type."})
                continue

            try:
                vehicle_id = uuid.UUID(message["vehicle_id"]) if message.get("vehicle_id") else None
                route_id = uuid.UUID(message["route_id"]) if message.get("route_id") else None
                db.expire_all()
                fresh_user = _authenticate(websocket, db)
                if fresh_user is None:
                    db.rollback()
                    await websocket.close(code=1008, reason="Access revoked.")
                    break
                topics = authorize_subscription(db, user, vehicle_id=vehicle_id, route_id=route_id)
                db.commit()
            except (ValueError, KeyError):
                db.rollback()
                await tracking_manager.send(websocket, {"type": "error", "code": "INVALID_ID", "message": "vehicle_id/route_id must be valid UUIDs."})
                continue
            except TrackingSubscriptionForbidden as exc:
                db.rollback()
                await tracking_manager.send(websocket, {"type": "error", "code": "FORBIDDEN", "message": str(exc)})
                continue

            if message_type == "subscribe":
                await tracking_manager.subscribe(websocket, topics)
                subscribed_topics.update(topics)
                await tracking_manager.send(websocket, {"type": "subscribed", "topics": sorted(topics)})
            else:
                await tracking_manager.unsubscribe(websocket, topics)
                subscribed_topics.difference_update(topics)
                await tracking_manager.send(websocket, {"type": "unsubscribed", "topics": sorted(topics)})

    except WebSocketDisconnect:
        pass
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
        await tracking_manager.disconnect(websocket)
        db.close()
        reset_organization(context_token)
