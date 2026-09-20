import json

import pytest

from app.dji.protocol import ProtocolError, make_reply, parse_envelope
from app.dji.topics import TopicKind, parse_topic, status_reply_topic


def test_status_topic_parser() -> None:
    parsed = parse_topic("sys/product/RC123/status")

    assert parsed.gateway_sn == "RC123"
    assert parsed.kind is TopicKind.STATUS
    assert status_reply_topic("RC123") == "sys/product/RC123/status_reply"


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


def test_protocol_rejects_missing_data() -> None:
    with pytest.raises(ProtocolError):
        parse_envelope(json.dumps({"tid": "t", "bid": "b", "timestamp": 1, "method": "x"}))
