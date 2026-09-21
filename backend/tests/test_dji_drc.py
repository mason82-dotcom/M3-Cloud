import json

import pytest

from app.dji.drc import DJIDRCStateStore
from app.dji.protocol import DRCMessage


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.published = []

    async def set(self, key, value, ex=None):
        self.values[key] = (value, ex)
        return True

    async def get(self, key):
        value = self.values.get(key)
        return value[0] if value else None

    async def publish(self, channel, payload):
        self.published.append((channel, payload))
        return 1


@pytest.mark.asyncio
async def test_drc_uplink_is_cached_and_published_losslessly():
    redis = FakeRedis()
    store = DJIDRCStateStore(redis)

    record = await store.update(
        "RC123",
        DRCMessage(
            method="drc_camera_osd_info_push",
            seq=7,
            timestamp=1234,
            data={
                "payload_index": "67-0-0",
                "wide_lense": {"wide_iso": 7},
                "future_dji_field": {"kept": True},
            },
        ),
    )

    assert record["method"] == "drc_camera_osd_info_push"
    assert record["seq"] == 7
    cached = await store.get_latest("RC123", "drc_camera_osd_info_push")
    assert cached["data"]["future_dji_field"] == {"kept": True}

    event = json.loads(redis.published[0][1])
    assert event["type"] == "dji_drc"
    assert event["device_sn"] == "RC123"
    assert event["drc"]["data"]["wide_lense"]["wide_iso"] == 7
