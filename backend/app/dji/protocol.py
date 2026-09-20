from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class Envelope:
    tid: str
    bid: str
    timestamp: int
    method: str
    data: dict[str, Any]


class ProtocolError(ValueError):
    """Raised when a DJI MQTT payload does not match the common envelope."""


def parse_envelope(payload: bytes | str | Mapping[str, Any]) -> Envelope:
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

    try:
        tid = decoded["tid"]
        bid = decoded["bid"]
        timestamp = decoded["timestamp"]
        method = decoded["method"]
        data = decoded["data"]
    except KeyError as exc:
        raise ProtocolError(f"missing envelope field: {exc.args[0]}") from exc

    if not isinstance(tid, str) or not tid:
        raise ProtocolError("tid must be a non-empty string")
    if not isinstance(bid, str) or not bid:
        raise ProtocolError("bid must be a non-empty string")
    if not isinstance(timestamp, int):
        raise ProtocolError("timestamp must be an integer")
    if not isinstance(method, str) or not method:
        raise ProtocolError("method must be a non-empty string")
    if not isinstance(data, dict):
        raise ProtocolError("data must be an object")

    return Envelope(
        tid=tid,
        bid=bid,
        timestamp=timestamp,
        method=method,
        data=data,
    )


def make_reply(
    envelope: Envelope,
    *,
    result: int = 0,
    timestamp_ms: int | None = None,
) -> dict[str, Any]:
    """Build the common DJI reply envelope while preserving request correlation IDs."""

    return {
        "tid": envelope.tid,
        "bid": envelope.bid,
        "timestamp": timestamp_ms if timestamp_ms is not None else int(time.time() * 1000),
        "method": envelope.method,
        "data": {
            "result": result,
        },
    }


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
        raise ProtocolError("DJI property payload must be a JSON object")

    timestamp = decoded.get("timestamp")
    data = decoded.get("data")
    if not isinstance(timestamp, int):
        raise ProtocolError("timestamp must be an integer")
    if not isinstance(data, dict):
        raise ProtocolError("data must be an object")

    def optional_text(name: str) -> str | None:
        value = decoded.get(name)
        return value if isinstance(value, str) and value else None

    return PropertyMessage(
        timestamp=timestamp,
        data=data,
        tid=optional_text("tid"),
        bid=optional_text("bid"),
        gateway=optional_text("gateway"),
        from_sn=optional_text("from"),
        need_reply=bool(decoded.get("need_reply", False)),
    )


def make_property_reply(
    message: PropertyMessage,
    *,
    result: int = 0,
    timestamp_ms: int | None = None,
) -> dict[str, Any]:
    """Build a DJI state/property acknowledgement when need_reply is set."""

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
    return reply
