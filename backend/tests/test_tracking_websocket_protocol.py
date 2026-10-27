import asyncio

from app.realtime.tracking_manager import TrackingConnectionManager


class FakeSocket:
    def __init__(self):
        self.events = []

    async def accept(self):
        pass

    async def send_json(self, event):
        self.events.append(event)


async def _broadcasts_only_to_subscribers():
    manager = TrackingConnectionManager()
    a, b = FakeSocket(), FakeSocket()
    await manager.connect(a)
    await manager.connect(b)
    manager._subscriptions[a] = {"vehicle:v1"}
    manager._subscriptions[b] = {"vehicle:v2"}
    await manager.broadcast({"type": "location_update"}, {"vehicle:v1"})
    assert len(a.events) == 1
    assert len(b.events) == 0


def test_broadcast_topic_isolation():
    asyncio.run(_broadcasts_only_to_subscribers())
