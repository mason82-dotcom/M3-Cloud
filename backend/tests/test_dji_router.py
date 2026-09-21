import json

import pytest

from app.dji.protocol import parse_envelope
from app.dji.router import DJIMessageRouter
from app.dji.topics import TopicKind
from app.dji.transactions import DJITransactionManager


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


@pytest.mark.asyncio
async def test_state_need_reply_is_acknowledged() -> None:
    registry = FakeRegistry()
    publisher = FakePublisher()
    telemetry = FakeTelemetry()
    router = DJIMessageRouter(registry, publisher, telemetry)

    payload = json.dumps(
        {
            "tid": "t-state",
            "bid": "b-state",
            "timestamp": 321,
            "gateway": "RC123",
            "from": "M3T123",
            "need_reply": 1,
            "data": {
                "home_latitude": 49.2,
                "home_longitude": 8.5,
            },
        }
    ).encode()

    await router.handle("thing/product/M3T123/state", payload)

    assert len(telemetry.calls) == 1
    assert len(publisher.messages) == 1

    topic, raw, qos, retain = publisher.messages[0]
    assert topic == "thing/product/M3T123/state_reply"
    assert qos == 0
    assert retain is False

    reply = json.loads(raw)
    assert reply["tid"] == "t-state"
    assert reply["bid"] == "b-state"
    assert reply["data"]["result"] == 0


@pytest.mark.asyncio
async def test_services_reply_resolves_registered_transaction() -> None:
    registry = FakeRegistry()
    publisher = FakePublisher()
    telemetry = FakeTelemetry()
    transactions = DJITransactionManager()
    router = DJIMessageRouter(
        registry,
        publisher,
        telemetry,
        transactions=transactions,
    )
    pending = transactions.register(TopicKind.SERVICES_REPLY, "RC123", "t-service")

    payload = json.dumps(
        {
            "tid": "t-service",
            "bid": "b-service",
            "timestamp": 500,
            "method": "live_start_push",
            "data": {"result": 0},
        }
    ).encode()

    await router.handle("thing/product/RC123/services_reply", payload)
    reply = await transactions.wait(pending, timeout_s=0.2)

    assert reply.method == "live_start_push"
    assert reply.data["result"] == 0
    assert transactions.pending_count == 0


@pytest.mark.asyncio
async def test_event_need_reply_uses_events_reply_topic() -> None:
    publisher = FakePublisher()
    router = DJIMessageRouter(FakeRegistry(), publisher, FakeTelemetry())

    await router.handle(
        "thing/product/RC123/events",
        json.dumps(
            {
                "tid": "t-event",
                "bid": "b-event",
                "timestamp": 600,
                "method": "cloud_control_auth_notify",
                "need_reply": 1,
                "data": {"result": 0},
            }
        ).encode(),
    )

    assert len(publisher.messages) == 1
    topic, raw, _, _ = publisher.messages[0]
    assert topic == "thing/product/RC123/events_reply"
    reply = parse_envelope(raw)
    assert reply.tid == "t-event"
    assert reply.data["result"] == 0


@pytest.mark.asyncio
async def test_unknown_device_request_fails_closed() -> None:
    publisher = FakePublisher()
    router = DJIMessageRouter(FakeRegistry(), publisher, FakeTelemetry())

    await router.handle(
        "thing/product/RC123/requests",
        json.dumps(
            {
                "tid": "t-request",
                "bid": "b-request",
                "timestamp": 700,
                "method": "unknown_server_capability",
                "data": {},
            }
        ).encode(),
    )

    assert len(publisher.messages) == 1
    topic, raw, _, _ = publisher.messages[0]
    assert topic == "thing/product/RC123/requests_reply"
    reply = parse_envelope(raw)
    assert reply.data["result"] != 0



class RaisingEvents:
    async def handle(self, gateway_sn, envelope):
        del gateway_sn, envelope
        raise RuntimeError("redis unavailable")


@pytest.mark.asyncio
async def test_event_handler_failure_still_returns_error_ack() -> None:
    publisher = FakePublisher()
    router = DJIMessageRouter(
        FakeRegistry(),
        publisher,
        FakeTelemetry(),
        events=RaisingEvents(),
    )

    await router.handle(
        "thing/product/RC123/events",
        json.dumps(
            {
                "tid": "t-event-fail",
                "bid": "b-event-fail",
                "timestamp": 601,
                "method": "drc_status_notify",
                "need_reply": 1,
                "data": {"result": 0, "drc_state": 2},
            }
        ).encode(),
    )

    assert len(publisher.messages) == 1
    topic, raw, _, _ = publisher.messages[0]
    assert topic == "thing/product/RC123/events_reply"
    reply = parse_envelope(raw)
    assert reply.data["result"] == 1
