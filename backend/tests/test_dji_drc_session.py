import asyncio
import json

import pytest

from app.config import Settings
from app.dji.drc import (
    DRC_UPLINK_SUBSCRIPTIONS,
    DJIDRCCommandChannel,
    DJIDRCSessionManager,
    DJIDRCTransport,
)


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



class FakeLifecycle:
    def __init__(self):
        self.starts = 0
        self.stops = 0

    async def start(self):
        self.starts += 1

    async def stop(self):
        self.stops += 1


@pytest.mark.asyncio
async def test_drc_session_starts_and_stops_dedicated_transport():
    publisher = FakePublisher()
    lifecycle = FakeLifecycle()
    manager = DJIDRCSessionManager(
        DJIDRCCommandChannel(publisher),
        heartbeat_interval_s=0.1,
        transport=lifecycle,
    )

    await manager.start("RC123")
    await manager.stop_all()

    assert lifecycle.starts == 1
    assert lifecycle.stops == 1


@pytest.mark.asyncio
async def test_drc_transport_uses_dedicated_broker_and_subscription(monkeypatch):
    created = []

    class FakeMQTT:
        def __init__(self, handler, **kwargs):
            self.handler = handler
            self.kwargs = kwargs
            self.connected = False
            self.published = []
            created.append(self)

        async def start(self):
            self.connected = True

        async def wait_connected(self, timeout_s):
            assert timeout_s == 5.0

        async def stop(self):
            self.connected = False

        async def publish(self, topic, payload, *, qos=0, retain=False):
            self.published.append((topic, payload, qos, retain))

    monkeypatch.setattr("app.dji.drc.DJIMqttTransport", FakeMQTT)

    async def handler(topic, payload):
        del topic, payload

    config = Settings(_env_file=None).model_copy(
        update={
            "dji_drc_broker_address": "192.168.178.45:1884",
            "dji_drc_client_id_prefix": "m3-drc-",
            "dji_drc_username": "drc-user",
            "dji_drc_password": "drc-pass",
            "dji_drc_enable_tls": True,
        }
    )
    transport = DJIDRCTransport(handler, config)

    await transport.start()
    await transport.publish(
        "thing/product/RC123/drc/down",
        b"{}",
    )
    await transport.stop()

    assert len(created) == 1
    mqtt = created[0]
    assert mqtt.kwargs["host"] == "192.168.178.45"
    assert mqtt.kwargs["port"] == 1884
    assert mqtt.kwargs["client_id"] == "m3-drc-backend"
    assert mqtt.kwargs["username"] == "drc-user"
    assert mqtt.kwargs["password"] == "drc-pass"
    assert mqtt.kwargs["subscriptions"] == DRC_UPLINK_SUBSCRIPTIONS
    assert mqtt.kwargs["tls_enabled"] is True
    assert mqtt.published[0][0] == "thing/product/RC123/drc/down"
