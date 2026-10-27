"""Authorized, topic-scoped WebSocket fan-out for single/multi-process API servers.

Redis Pub/Sub is the optional shared transport. Each worker listens once on
startup and independently delivers ONLY to its own authorized subscriptions.
No Redis is needed for the supported single-worker local demo.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any
from uuid import UUID

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class TrackingConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._subscriptions: dict[WebSocket, set[str]] = defaultdict(set)
        self._send_locks: dict[WebSocket, asyncio.Lock] = {}
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._redis = None
        self._listener: asyncio.Task | None = None
        self._channel: str | None = None
        self._ready: asyncio.Event | None = None

    async def start(self, *, redis_url: str = "", channel: str = "medwaste:tracking:events:v1") -> None:
        """Start at application lifespan startup, even if no WS client connects."""
        self._loop = asyncio.get_running_loop()
        if not redis_url:
            return
        if self._redis is not None:
            return
        try:
            from redis.asyncio import Redis
        except ImportError as exc:
            raise RuntimeError("Redis URL configured but redis client is not installed") from exc
        client = Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=3, socket_timeout=5)
        try:
            await client.ping()  # fail startup rather than silently dropping cross-worker events
        except Exception:
            await client.aclose()
            raise
        self._redis = client
        self._channel = channel
        self._ready = asyncio.Event()
        self._listener = asyncio.create_task(self._listen(), name="medwaste-tracking-redis-listener")
        # A publisher cannot safely emit until the current process is actually
        # subscribed; otherwise the initial cross-worker messages are lost.
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=5)
        except Exception:
            await self.stop()
            raise RuntimeError('Could not subscribe to Redis tracking channel at startup')

    async def stop(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            try:
                await self._listener
            except asyncio.CancelledError:
                pass
            self._listener = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        self._channel = None
        self._ready = None
        self._loop = None

    async def _listen(self) -> None:
        """Reconnect on transient Redis failure; don't silently fall back to local-only."""
        while self._redis is not None:
            try:
                async with self._redis.pubsub(ignore_subscribe_messages=True) as pubsub:
                    await pubsub.subscribe(self._channel)
                    if self._ready is not None:
                        self._ready.set()
                    async for message in pubsub.listen():
                        if message.get('type') != 'message':
                            continue
                        try:
                            packet = json.loads(message['data'])
                            if packet.get('v') != 1:
                                continue
                            topics = packet.get('topics')
                            event = packet.get('event')
                            if (not isinstance(topics, list) or not topics or len(topics) > 100
                                    or not all(isinstance(t, str) and (t.startswith('vehicle:') or t.startswith('route:')) for t in topics)
                                    or not isinstance(event, dict)):
                                continue
                            await self._broadcast_local(event, set(topics))
                        except (ValueError, TypeError, KeyError):
                            logger.warning('Rejected malformed tracking event from Redis')
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Tracking Redis listener disconnected; retrying')
                await asyncio.sleep(1.0)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
            self._subscriptions[websocket] = set()
            self._send_locks[websocket] = asyncio.Lock()
        logger.info("Tracking WebSocket connected")

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
            self._subscriptions.pop(websocket, None)
            self._send_locks.pop(websocket, None)
        logger.info("Tracking WebSocket disconnected")

    async def subscribe(self, websocket: WebSocket, topics: set[str]) -> None:
        async with self._lock:
            if websocket in self._connections:
                self._subscriptions[websocket].update(topics)

    async def unsubscribe(self, websocket: WebSocket, topics: set[str]) -> None:
        async with self._lock:
            self._subscriptions[websocket].difference_update(topics)

    async def _broadcast_local(self, event: dict[str, Any], topics: set[str]) -> None:
        async with self._lock:
            recipients = [ws for ws in self._connections if self._subscriptions.get(ws, set()) & topics]
        for ws in recipients:
            await self.send(ws, event)

    async def broadcast(self, event: dict[str, Any], topics: set[str]) -> None:
        if not topics:
            return
        if self._redis is None:
            await self._broadcast_local(event, topics)
            return
        # All workers (including the publishing worker) receive the one Redis
        # event, so do NOT also send it locally and double-deliver.
        try:
            await self._redis.publish(self._channel, json.dumps({
                'v': 1, 'topics': sorted(topics), 'event': event}, separators=(',', ':'), default=str))
        except Exception:
            logger.exception('Failed to publish cross-worker tracking update')
            # During a Redis outage, make best-effort local delivery to avoid
            # losing the dashboard on the current worker. Remote delivery is
            # NOT guaranteed until the shared broker recovers.
            await self._broadcast_local(event, topics)

    def broadcast_from_sync(self, event: dict[str, Any], topics: set[str]) -> None:
        """Schedule from sync routes running in FastAPI's threadpool.

        Startup owns the loop: relying on first socket connection would drop
        publications from an API process with no WebSocket clients.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            logger.warning('Tracking broadcast ignored: server lifespan has not started')
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(event, topics), loop)

    async def send(self, websocket: WebSocket, event: dict[str, Any]) -> None:
        # Redis listener and heartbeat can send to the same socket concurrently.
        # Serialize socket writes without holding the global subscription lock.
        lock = self._send_locks.get(websocket)
        if lock is None:
            return
        try:
            async with lock:
                await websocket.send_json(event)
        except Exception:
            await self.disconnect(websocket)

    async def snapshot(self) -> dict[str, int]:
        async with self._lock:
            return {'connections': len(self._connections)}


tracking_manager = TrackingConnectionManager()


def vehicle_topic(vehicle_id: UUID | str) -> str:
    return f'vehicle:{vehicle_id}'


def route_topic(route_id: UUID | str) -> str:
    return f'route:{route_id}'
