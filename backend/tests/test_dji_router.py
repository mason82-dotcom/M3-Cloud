import json

import pytest

from app.dji.router import DJIMessageRouter


class FakeRegistry:
    def __init__(self) -> None:
        self.calls = []

    async def update_topology(self, gateway_sn, envelope):
        self.calls.append((gateway_sn, envelope))
        return None


class FakePublisher:
    def __init__(self) -> None:
        self.messages = []

    async def publish(self, topic, payload, *, qos=0, retain=False):
        self.messages.append((topic, payload, qos, retain))


@pytest.mark.asyncio
async def test_update_topo_is_persisted_before_ack() -> None:
    registry = FakeRegistry()
    publisher = FakePublisher()
    router = DJIMessageRouter(registry, publisher)

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
