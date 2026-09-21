import asyncio
import json

import pytest

from app.dji.drc import DJIDRCCommandChannel, DJIDRCSessionManager


class FakePublisher:
    def __init__(self):
        self.messages = []

    async def publish(self, topic, payload, *, qos=0, retain=False):
        self.messages.append((topic, json.loads(payload), qos, retain))


@pytest.mark.asyncio
async def test_drc_channel_sequences_packets_per_gateway():
    publisher = FakePublisher()
    channel = DJIDRCCommandChannel(publisher)

    first = await channel.send("RC123", "drc_initial_state_subscribe", {})
    second = await channel.send(
        "RC123",
        "heart_beat",
        {"timestamp": 1234},
    )

    assert (first, second) == (1, 2)
    assert publisher.messages[0][0] == "thing/product/RC123/drc/down"
    assert publisher.messages[0][1] == {
        "method": "drc_initial_state_subscribe",
        "seq": 1,
        "data": {},
    }
    assert publisher.messages[1][1]["method"] == "heart_beat"
    assert publisher.messages[1][1]["seq"] == 2
    assert publisher.messages[1][2:] == (0, False)


@pytest.mark.asyncio
async def test_drc_session_subscribes_state_and_keeps_heartbeat_alive():
    publisher = FakePublisher()
    manager = DJIDRCSessionManager(
        DJIDRCCommandChannel(publisher),
        heartbeat_interval_s=0.1,
    )

    await manager.start("RC123")
    try:
        for _ in range(20):
            if len(publisher.messages) >= 2:
                break
            await asyncio.sleep(0.01)

        methods = [item[1]["method"] for item in publisher.messages]
        assert methods[0] == "drc_initial_state_subscribe"
        assert "heart_beat" in methods
        assert manager.active_gateways == ("RC123",)
    finally:
        await manager.stop_all()

    assert manager.active_gateways == ()
