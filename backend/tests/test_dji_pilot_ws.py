import asyncio
import json

import pytest

from app.dji.pilot_ws import DJIPilotWebSocketHub


class FakeWebSocket:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.accepted = False
        self.closed = []
        self.messages = []

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000):
        self.closed.append(code)

    async def send_json(self, payload):
        if self.fail:
            raise RuntimeError("socket closed")
        self.messages.append(payload)


class FakePubSub:
    def __init__(self, events):
        self.events = list(events)
        self.subscribed = []
        self.closed = False
        self._hold = asyncio.Event()

    async def subscribe(self, channel):
        self.subscribed.append(channel)

    async def listen(self):
        for event in self.events:
            yield event
        await self._hold.wait()

    async def aclose(self):
        self.closed = True
        self._hold.set()


class FakeRedis:
    def __init__(self, events):
        self.pubsub_instance = FakePubSub(events)

    def pubsub(self):
        return self.pubsub_instance


@pytest.mark.asyncio
async def test_pilot_ws_hub_translates_redis_telemetry_to_dji_osd():
    event = {
        "type": "telemetry",
        "device_sn": "M3T123",
        "timestamp": 123456789,
        "state": {
            "latitude": 49.1,
            "longitude": 8.4,
            "ellipsoid_height_m": 142.5,
            "relative_altitude_m": 50.0,
            "horizontal_speed_mps": 7.2,
            "vertical_speed_mps": -0.2,
            "attitude": {"yaw_deg": 91.0},
        },
    }
    redis = FakeRedis(
        [
            {
                "type": "message",
                "data": json.dumps(event).encode("utf-8"),
            }
        ]
    )
    hub = DJIPilotWebSocketHub(redis, channel="m3:live")
    websocket = FakeWebSocket()

    await hub.connect(websocket)
    await hub.start()
    for _ in range(50):
        if websocket.messages:
            break
        await asyncio.sleep(0)

    try:
        assert websocket.accepted is True
        assert redis.pubsub_instance.subscribed == ["m3:live"]
        assert websocket.messages == [
            {
                "biz_code": "device_osd",
                "version": "1.0",
                "timestamp": 123456789,
                "data": {
                    "host": {
                        "latitude": 49.1,
                        "longitude": 8.4,
                        "height": 142.5,
                        "attitude_head": 91.0,
                        "elevation": 50.0,
                        "horizontal_speed": 7.2,
                        "vertical_speed": -0.2,
                    },
                    "sn": "M3T123",
                },
            }
        ]
    finally:
        await hub.stop()

    assert redis.pubsub_instance.closed is True
    assert websocket.closed == [1001]


@pytest.mark.asyncio
async def test_pilot_ws_hub_drops_failed_connections_without_blocking_healthy_ones():
    hub = DJIPilotWebSocketHub(FakeRedis([]), channel="m3:live")
    healthy = FakeWebSocket()
    failed = FakeWebSocket(fail=True)
    hub.connections.update({healthy, failed})

    await hub.broadcast(
        {
            "biz_code": "device_update_topo",
            "version": "1.0",
            "timestamp": 1,
            "data": {},
        }
    )

    assert healthy.messages[0]["biz_code"] == "device_update_topo"
    assert failed not in hub.connections
    assert healthy in hub.connections
