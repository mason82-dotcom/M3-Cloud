from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CorrelatedMessage:
    tid: str
    bid: str
    timestamp: int
    data: dict[str, Any]
    gateway: str | None = None


@dataclass(frozen=True)
class Envelope(CorrelatedMessage):
    method: str = ""
    need_reply: bool = False


class ProtocolError(ValueError):
    """Raised when a DJI MQTT payload does not match the documented envelope."""


def _decode_object(payload: bytes | str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        try:
            decoded: Any = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"invalid JSON: {exc.msg}") from exc
    else:
        decoded = dict(payload)

    if not isinstance(decoded, dict):
        raise ProtocolError("DJI payload must be a JSON object")
    return decoded


def _required_text(decoded: Mapping[str, Any], name: str) -> str:
    value = decoded.get(name)
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"{name} must be a non-empty string")
    return value


def _optional_text(decoded: Mapping[str, Any], name: str) -> str | None:
    value = decoded.get(name)
    return value if isinstance(value, str) and value else None


def parse_correlated_message(
    payload: bytes | str | Mapping[str, Any],
) -> CorrelatedMessage:
    decoded = _decode_object(payload)
    timestamp = decoded.get("timestamp")
    data = decoded.get("data")

    if not isinstance(timestamp, int) or isinstance(timestamp, bool):
        raise ProtocolError("timestamp must be an integer")
    if not isinstance(data, dict):
        raise ProtocolError("data must be an object")

    return CorrelatedMessage(
        tid=_required_text(decoded, "tid"),
        bid=_required_text(decoded, "bid"),
        timestamp=timestamp,
        data=data,
        gateway=_optional_text(decoded, "gateway"),
    )


def parse_envelope(payload: bytes | str | Mapping[str, Any]) -> Envelope:
    decoded = _decode_object(payload)
    correlated = parse_correlated_message(decoded)
    method = _required_text(decoded, "method")

    return Envelope(
        tid=correlated.tid,
        bid=correlated.bid,
        timestamp=correlated.timestamp,
        data=correlated.data,
        gateway=correlated.gateway,
        method=method,
        need_reply=bool(decoded.get("need_reply", False)),
    )


def make_correlated_message(
    data: Mapping[str, Any],
    *,
    tid: str | None = None,
    bid: str | None = None,
    timestamp_ms: int | None = None,
    gateway: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tid": tid or str(uuid.uuid4()),
        "bid": bid or str(uuid.uuid4()),
        "timestamp": timestamp_ms if timestamp_ms is not None else int(time.time() * 1000),
        "data": dict(data),
    }
    if gateway:
        payload["gateway"] = gateway
    return payload


def make_message(
    method: str,
    data: Mapping[str, Any],
    *,
    tid: str | None = None,
    bid: str | None = None,
    timestamp_ms: int | None = None,
    gateway: str | None = None,
    need_reply: bool | None = None,
) -> dict[str, Any]:
    if not method:
        raise ValueError("DJI method cannot be empty")

    payload = make_correlated_message(
        data,
        tid=tid,
        bid=bid,
        timestamp_ms=timestamp_ms,
        gateway=gateway,
    )
    payload["method"] = method
    if need_reply is not None:
        payload["need_reply"] = int(bool(need_reply))
    return payload


def make_reply(
    envelope: Envelope,
    *,
    result: int = 0,
    output: Mapping[str, Any] | None = None,
    timestamp_ms: int | None = None,
) -> dict[str, Any]:
    """Build a DJI reply while preserving transaction and business IDs."""

    data: dict[str, Any] = {"result": int(result)}
    if output is not None:
        data["output"] = dict(output)

    return make_message(
        envelope.method,
        data,
        tid=envelope.tid,
        bid=envelope.bid,
        timestamp_ms=timestamp_ms,
        gateway=envelope.gateway,
    )


def encode_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class PropertyMessage:
    """Common uplink envelope used by DJI OSD/state property topics."""

    timestamp: int
    data: dict[str, Any]
    tid: str | None = None
    bid: str | None = None
    gateway: str | None = None
    from_sn: str | None = None
    need_reply: bool = False


def parse_property_message(payload: bytes | str | Mapping[str, Any]) -> PropertyMessage:
    """Parse OSD/state payloads, which intentionally do not require a method field."""

    decoded = _decode_object(payload)
    timestamp = decoded.get("timestamp")
    data = decoded.get("data")
    if not isinstance(timestamp, int) or isinstance(timestamp, bool):
        raise ProtocolError("timestamp must be an integer")
    if not isinstance(data, dict):
        raise ProtocolError("data must be an object")

    return PropertyMessage(
        timestamp=timestamp,
        data=data,
        tid=_optional_text(decoded, "tid"),
        bid=_optional_text(decoded, "bid"),
        gateway=_optional_text(decoded, "gateway"),
        from_sn=_optional_text(decoded, "from"),
        need_reply=bool(decoded.get("need_reply", False)),
    )


def make_property_reply(
    message: PropertyMessage,
    *,
    result: int = 0,
    timestamp_ms: int | None = None,
) -> dict[str, Any]:
    """Build a DJI state acknowledgement when need_reply is set."""

    reply: dict[str, Any] = {
        "timestamp": timestamp_ms if timestamp_ms is not None else int(time.time() * 1000),
        "data": {
            "result": result,
        },
    }
    if message.tid is not None:
        reply["tid"] = message.tid
    if message.bid is not None:
        reply["bid"] = message.bid
    if message.gateway is not None:
        reply["gateway"] = message.gateway
    return reply



@dataclass(frozen=True)
class DRCMessage:
    """DJI DRC uplink/downlink envelope.

    DRC traffic is intentionally separate from the normal TID/BID service
    envelope. DJI documents method/data plus optional sequence/timestamp fields.
    """

    method: str
    data: dict[str, Any]
    seq: int | None = None
    timestamp: int | None = None


def parse_drc_message(
    payload: bytes | str | Mapping[str, Any],
) -> DRCMessage:
    decoded = _decode_object(payload)
    method = _required_text(decoded, "method")
    data = decoded.get("data")
    if not isinstance(data, dict):
        raise ProtocolError("DRC data must be an object")

    seq = decoded.get("seq")
    if seq is not None and (
        not isinstance(seq, int) or isinstance(seq, bool)
    ):
        raise ProtocolError("DRC seq must be an integer")

    timestamp = decoded.get("timestamp")
    if timestamp is not None and (
        not isinstance(timestamp, int) or isinstance(timestamp, bool)
    ):
        raise ProtocolError("DRC timestamp must be an integer")

    return DRCMessage(
        method=method,
        data=dict(data),
        seq=seq,
        timestamp=timestamp,
    )
