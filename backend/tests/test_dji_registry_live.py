import json

import pytest

from app.dji.protocol import parse_envelope
from app.dji.registry import DeviceRegistry


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.ops = []

    def set(self, key, value):
        self.ops.append(("set", key, value))
        return self

    def delete(self, key):
        self.ops.append(("delete", key))
        return self

    def sadd(self, key, *values):
        self.ops.append(("sadd", key, values))
        return self

    async def execute(self):
        for op in self.ops:
            if op[0] == "set":
                self.redis.values[op[1]] = op[2]
            elif op[0] == "delete":
                self.redis.sets.pop(op[1], None)
            elif op[0] == "sadd":
                self.redis.sets.setdefault(op[1], set()).update(op[2])
        return []


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.sets = {}
        self.published = []

    async def smembers(self, key):
        return self.sets.get(key, set())

    async def get(self, key):
        return self.values.get(key)

    def pipeline(self, transaction=True):
        assert transaction is True
        return FakePipeline(self)

    async def publish(self, channel, payload):
        self.published.append((channel, json.loads(payload)))
        return 1


def topo(children):
    return parse_envelope(
        {
            "tid": "t",
            "bid": "b",
            "timestamp": 1,
            "method": "update_topo",
            "data": {
                "domain": "2",
                "type": 144,
                "sub_type": 0,
                "sub_devices": children,
            },
        }
    )


@pytest.mark.asyncio
async def test_topology_emits_online_and_topology_events() -> None:
    redis = FakeRedis()
    registry = DeviceRegistry(redis)

    await registry.update_topology(
        "RC123",
        topo(
            [
                {
                    "sn": "M3E123",
                    "domain": "0",
                    "type": 77,
                    "sub_type": 0,
                }
            ]
        ),
    )

    event_types = [event["type"] for _, event in redis.published]
    assert event_types == ["device_online", "device_online", "topology"]

    topology = redis.published[-1][1]
    assert topology["gateway_sn"] == "RC123"
    assert {device["sn"] for device in topology["devices"]} == {"RC123", "M3E123"}


@pytest.mark.asyncio
async def test_removed_aircraft_emits_offline_event() -> None:
    redis = FakeRedis()
    registry = DeviceRegistry(redis)

    await registry.update_topology(
        "RC123",
        topo(
            [
                {
                    "sn": "M3T123",
                    "domain": "0",
                    "type": 77,
                    "sub_type": 1,
                }
            ]
        ),
    )
    redis.published.clear()

    await registry.update_topology("RC123", topo([]))

    event_types = [event["type"] for _, event in redis.published]
    assert event_types == ["device_offline", "topology"]

    offline = redis.published[0][1]["device"]
    assert offline["sn"] == "M3T123"
    assert offline["online"] is False
