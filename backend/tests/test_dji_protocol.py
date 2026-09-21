import json

import pytest

from app.dji.protocol import (
    ProtocolError,
    make_message,
    make_property_reply,
    make_reply,
    parse_drc_message,
    parse_envelope,
    parse_property_message,
)
from app.dji.topics import (
    SUBSCRIPTIONS,
    TopicDirection,
    TopicKind,
    parse_topic,
    status_reply_topic,
)


def test_status_topic_parser() -> None:
    parsed = parse_topic("sys/product/RC123/status")

    assert parsed.gateway_sn == "RC123"
    assert parsed.kind is TopicKind.STATUS
    assert parsed.direction is TopicDirection.UPLINK
    assert status_reply_topic("RC123") == "sys/product/RC123/status_reply"


def test_subscription_set_contains_only_dji_uplink_topics() -> None:
    assert "thing/product/+/services_reply" in SUBSCRIPTIONS
    assert "thing/product/+/events" in SUBSCRIPTIONS
    assert "thing/product/+/requests" in SUBSCRIPTIONS
    assert "thing/product/+/property/set_reply" in SUBSCRIPTIONS
    assert "thing/product/+/drc/up" in SUBSCRIPTIONS

    assert "thing/product/+/services" not in SUBSCRIPTIONS
    assert "thing/product/+/events_reply" not in SUBSCRIPTIONS
    assert "thing/product/+/requests_reply" not in SUBSCRIPTIONS
    assert "thing/product/+/property/set" not in SUBSCRIPTIONS
    assert "thing/product/+/drc/down" not in SUBSCRIPTIONS


def test_topic_direction_is_explicit() -> None:
    assert parse_topic("thing/product/RC/services").direction is TopicDirection.DOWNLINK
    assert parse_topic("thing/product/RC/services_reply").direction is TopicDirection.UPLINK
    assert parse_topic("thing/product/RC/drc/up").kind is TopicKind.DRC_UP
    assert parse_topic("thing/product/RC/drc/down").kind is TopicKind.DRC_DOWN


def test_update_topo_envelope_and_reply_keep_correlation_ids() -> None:
    envelope = parse_envelope(
        {
            "tid": "t-1",
            "bid": "b-1",
            "timestamp": 123,
            "method": "update_topo",
            "data": {"type": 144, "sub_type": 0, "sub_devices": []},
        }
    )

    reply = make_reply(envelope, timestamp_ms=456)

    assert reply == {
        "tid": "t-1",
        "bid": "b-1",
        "timestamp": 456,
        "method": "update_topo",
        "data": {"result": 0},
    }


def test_make_message_builds_service_envelope() -> None:
    payload = make_message(
        "live_start_push",
        {"video_id": "M3T/67-0-0/normal-0"},
        tid="t",
        bid="b",
        timestamp_ms=123,
    )

    assert payload == {
        "tid": "t",
        "bid": "b",
        "timestamp": 123,
        "data": {"video_id": "M3T/67-0-0/normal-0"},
        "method": "live_start_push",
    }


def test_protocol_rejects_missing_data() -> None:
    with pytest.raises(ProtocolError):
        parse_envelope(json.dumps({"tid": "t", "bid": "b", "timestamp": 1, "method": "x"}))


def test_property_message_does_not_require_method() -> None:
    message = parse_property_message(
        {
            "tid": "t",
            "bid": "b",
            "timestamp": 1234,
            "gateway": "RC123",
            "from": "M3E123",
            "data": {
                "elevation": 10.5,
                "height": 120.7,
            },
        }
    )

    assert message.gateway == "RC123"
    assert message.from_sn == "M3E123"
    assert message.data["elevation"] == 10.5


def test_property_reply_keeps_correlation_ids() -> None:
    message = parse_property_message(
        {
            "tid": "t-state",
            "bid": "b-state",
            "timestamp": 1,
            "need_reply": 1,
            "data": {"home_latitude": 49.2},
        }
    )

    reply = make_property_reply(message, timestamp_ms=2)

    assert reply == {
        "tid": "t-state",
        "bid": "b-state",
        "timestamp": 2,
        "data": {"result": 0},
    }



def test_drc_message_parser_keeps_drc_sequence_separate_from_service_envelope():
    message = parse_drc_message(
        {
            "method": "drc_drone_state_push",
            "seq": 42,
            "timestamp": 1700000000000,
            "data": {
                "mode_code": 17,
                "night_lights_state": 1,
            },
        }
    )

    assert message.method == "drc_drone_state_push"
    assert message.seq == 42
    assert message.timestamp == 1700000000000
    assert message.data["mode_code"] == 17


@pytest.mark.parametrize(
    "payload",
    [
        {"method": "", "data": {}},
        {"method": "heart_beat", "data": []},
        {"method": "heart_beat", "data": {}, "seq": True},
        {"method": "heart_beat", "data": {}, "timestamp": "bad"},
    ],
)
def test_drc_message_parser_fails_closed_on_invalid_envelope(payload):
    with pytest.raises(ProtocolError):
        parse_drc_message(payload)
