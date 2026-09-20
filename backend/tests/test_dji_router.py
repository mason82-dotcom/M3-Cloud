import json

import pytest

from app.dji.router import DJIMessageRouter


class FakeRegistry:
    def __init__(self) -> None:
        self.calls = []

    async def update_topology(self, gateway_sn, envelope):
        self.calls.append((gateway_sn, envelope))
        return None


class FakeTelemetry:
    def __init__(self) -> None:
        self.calls = []

    async def update(self, **kwargs):
        self.calls.append(kwargs)
        return {}


class FakePublisher:
    def __init__(self) -> None:
        self.messages = []

    async def publish(self, topic, payload, *, qos=0, retain=False):
        self.messages.append((topic, payload, qos, retain))


@pytest.mark.asyncio
async def test_update_topo_is_persisted_before_ack() -> None:
    registry = FakeRegistry()
    publisher = FakePublisher()
    telemetry = FakeTelemetry()
    router = DJIMessageRouter(registry, publisher, telemetry)

    payload = json.dumps(
        {
            "tid": "t1",
            "bid": "b1",
            "timestamp": 123,
            "method": "update_topo",
            "data": {
                "domain": "2",
                "type": 144,
                "sub_type": 0,
                "sub_devices": [],
            },
        }
    ).encode()

    await router.handle("sys/product/RC123/status", payload)

    assert len(registry.calls) == 1
    assert registry.calls[0][0] == "RC123"
    assert len(publisher.messages) == 1

    topic, raw, qos, retain = publisher.messages[0]
    assert topic == "sys/product/RC123/status_reply"
    assert qos == 0
    assert retain is False

    reply = json.loads(raw)
    assert reply["tid"] == "t1"
    assert reply["bid"] == "b1"
    assert reply["method"] == "update_topo"
    assert reply["data"]["result"] == 0


@pytest.mark.asyncio
async def test_osd_uses_property_parser_and_telemetry_store() -> None:
    registry = FakeRegistry()
    publisher = FakePublisher()
    telemetry = FakeTelemetry()
    router = DJIMessageRouter(registry, publisher, telemetry)

    payload = json.dumps(
        {
            "tid": "t-osd",
            "bid": "b-osd",
            "timestamp": 123,
            "gateway": "RC123",
            "from": "M3E123",
            "data": {
                "elevation": 42.0,
                "height": 150.0,
                "position_state": {
                    "is_fixed": 1,
                    "gps_number": 20,
                    "rtk_number": 28,
                },
            },
        }
    ).encode()

    await router.handle("thing/product/M3E123/osd", payload)

    assert len(telemetry.calls) == 1
    assert telemetry.calls[0]["source_sn"] == "M3E123"
    assert telemetry.calls[0]["kind"].value == "osd"
    assert telemetry.calls[0]["message"].gateway == "RC123"
    assert publisher.messages == []
