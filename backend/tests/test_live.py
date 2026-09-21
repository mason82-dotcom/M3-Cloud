import asyncio
import pytest

from app.live import LiveTelemetryHub


class FakeWebSocket:
    def __init__(self, *, fail=False, hang=False):
        self.fail = fail
        self.hang = hang
        self.accepted = False
        self.messages = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        if self.fail:
            raise RuntimeError("socket closed")
        if self.hang:
            await asyncio.Event().wait()
        self.messages.append(payload)


class FakeRedis:
    pass


@pytest.mark.asyncio
async def test_live_hub_connect_and_broadcast() -> None:
    hub = LiveTelemetryHub(FakeRedis())
    websocket = FakeWebSocket()

    await hub.connect(websocket)
    await hub.broadcast(
        {
            "type": "telemetry",
            "device_sn": "M3E123",
            "state": {"latitude": 49.1},
        }
    )

    assert websocket.accepted is True
    assert websocket.messages[0] == {
        "type": "connected",
        "channel": "telemetry",
    }
    assert websocket.messages[1]["device_sn"] == "M3E123"


@pytest.mark.asyncio
async def test_live_hub_drops_failed_socket() -> None:
    hub = LiveTelemetryHub(FakeRedis())
    websocket = FakeWebSocket()
    hub.connections.add(websocket)
    websocket.fail = True

    await hub.broadcast({"type": "telemetry"})

    assert websocket not in hub.connections


@pytest.mark.asyncio
async def test_live_hub_slow_socket_cannot_block_healthy_clients() -> None:
    hub = LiveTelemetryHub(FakeRedis(), send_timeout_s=0.05)
    healthy = FakeWebSocket()
    slow = FakeWebSocket(hang=True)
    hub.connections.update({healthy, slow})

    await asyncio.wait_for(
        hub.broadcast({"type": "telemetry", "device_sn": "M3T123"}),
        timeout=0.2,
    )

    assert healthy.messages[0]["device_sn"] == "M3T123"
    assert healthy in hub.connections
    assert slow not in hub.connections
