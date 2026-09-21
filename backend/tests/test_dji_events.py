import json

import pytest

from app.dji.events import DJIEventDispatcher, DJIEventStateStore
from app.dji.protocol import Envelope


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.published = []

    async def set(self, key, value, ex=None):
        del ex
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def publish(self, channel, payload):
        self.published.append((channel, payload))
        return 1


def envelope(method, data, *, bid="bid", need_reply=True):
    return Envelope(
        tid="tid",
        bid=bid,
        timestamp=1234,
        data=data,
        gateway="RC123",
        method=method,
        need_reply=need_reply,
    )


@pytest.mark.asyncio
async def test_cloud_control_auth_notify_is_persisted_and_published():
    redis = FakeRedis()
    store = DJIEventStateStore(redis)

    result = await store.cloud_control_auth_notify(
        "RC123",
        envelope(
            "cloud_control_auth_notify",
            {"result": 0, "output": {"status": "ok"}},
        ),
    )

    assert result == 0
    saved = json.loads(
        redis.values["dji:event:RC123:cloud_control_auth_notify"]
    )
    assert saved["data"]["output"]["status"] == "ok"
    assert saved["bid"] == "bid"
    assert len(redis.published) == 1
    event = json.loads(redis.published[0][1])
    assert event["type"] == "dji_event"
    assert event["event"]["method"] == "cloud_control_auth_notify"


@pytest.mark.asyncio
async def test_drc_status_notify_validates_state_enum():
    redis = FakeRedis()
    store = DJIEventStateStore(redis)

    assert await store.drc_status_notify(
        "RC123",
        envelope("drc_status_notify", {"result": 0, "drc_state": 2}),
    ) == 0
    assert await store.drc_status_notify(
        "RC123",
        envelope("drc_status_notify", {"result": 0, "drc_state": 9}),
    ) == 1


@pytest.mark.asyncio
async def test_photo_progress_is_partitioned_by_business_id():
    redis = FakeRedis()
    store = DJIEventStateStore(redis)

    result = await store.camera_photo_take_progress(
        "RC123",
        envelope(
            "camera_photo_take_progress",
            {
                "result": 0,
                "output": {
                    "status": "in_progress",
                    "progress": {
                        "current_step": 3002,
                        "percent": 45,
                    },
                    "ext": {"camera_mode": 3},
                },
            },
            bid="capture-1",
        ),
    )

    assert result == 0
    specific = await store.get_photo_progress("RC123", "capture-1")
    assert specific["data"]["output"]["progress"]["percent"] == 45


@pytest.mark.asyncio
async def test_invalid_photo_progress_is_rejected_without_persistence():
    redis = FakeRedis()
    store = DJIEventStateStore(redis)

    result = await store.camera_photo_take_progress(
        "RC123",
        envelope(
            "camera_photo_take_progress",
            {
                "result": 0,
                "output": {
                    "status": "in_progress",
                    "progress": {
                        "current_step": 3002,
                        "percent": 101,
                    },
                },
            },
        ),
    )

    assert result == 1
    assert redis.values == {}
    assert redis.published == []


@pytest.mark.asyncio
async def test_register_binds_all_documented_rc_pro_events():
    redis = FakeRedis()
    store = DJIEventStateStore(redis)
    dispatcher = DJIEventDispatcher()
    store.register(dispatcher)

    for method, data in (
        (
            "cloud_control_auth_notify",
            {"result": 0, "output": {"status": "ok"}},
        ),
        (
            "drc_status_notify",
            {"result": 0, "drc_state": 2},
        ),
        (
            "camera_photo_take_progress",
            {
                "result": 0,
                "output": {
                    "status": "ok",
                    "progress": {"current_step": 3000, "percent": 100},
                },
            },
        ),
    ):
        assert await dispatcher.handle("RC123", envelope(method, data)) == 0
