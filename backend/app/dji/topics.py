from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TopicDirection(StrEnum):
    UPLINK = "uplink"
    DOWNLINK = "downlink"


class TopicKind(StrEnum):
    STATUS = "status"
    STATUS_REPLY = "status_reply"
    OSD = "osd"
    STATE = "state"
    STATE_REPLY = "state_reply"
    EVENTS = "events"
    EVENTS_REPLY = "events_reply"
    REQUESTS = "requests"
    REQUESTS_REPLY = "requests_reply"
    SERVICES = "services"
    SERVICES_REPLY = "services_reply"
    PROPERTY_SET = "property_set"
    PROPERTY_SET_REPLY = "property_set_reply"
    DRC_UP = "drc_up"
    DRC_DOWN = "drc_down"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ParsedTopic:
    raw: str
    device_sn: str | None
    kind: TopicKind
    direction: TopicDirection | None

    @property
    def gateway_sn(self) -> str | None:
        """Compatibility alias: gateway-scoped topics use device_sn as gateway SN."""

        return self.device_sn


# Only Device -> Cloud topics belong in the server subscription set.
# Cloud -> Device topics are publish-only and must never be subscribed by M3-Cloud.
UPLINK_SUBSCRIPTIONS: tuple[str, ...] = (
    "sys/product/+/status",
    "thing/product/+/osd",
    "thing/product/+/state",
    "thing/product/+/events",
    "thing/product/+/requests",
    "thing/product/+/services_reply",
    "thing/product/+/property/set_reply",
)

# Backwards-compatible name used by the MQTT transport.
SUBSCRIPTIONS = UPLINK_SUBSCRIPTIONS


_THING_SUFFIXES: dict[str, tuple[TopicKind, TopicDirection]] = {
    "osd": (TopicKind.OSD, TopicDirection.UPLINK),
    "state": (TopicKind.STATE, TopicDirection.UPLINK),
    "state_reply": (TopicKind.STATE_REPLY, TopicDirection.DOWNLINK),
    "events": (TopicKind.EVENTS, TopicDirection.UPLINK),
    "events_reply": (TopicKind.EVENTS_REPLY, TopicDirection.DOWNLINK),
    "requests": (TopicKind.REQUESTS, TopicDirection.UPLINK),
    "requests_reply": (TopicKind.REQUESTS_REPLY, TopicDirection.DOWNLINK),
    "services": (TopicKind.SERVICES, TopicDirection.DOWNLINK),
    "services_reply": (TopicKind.SERVICES_REPLY, TopicDirection.UPLINK),
    "property/set": (TopicKind.PROPERTY_SET, TopicDirection.DOWNLINK),
    "property/set_reply": (TopicKind.PROPERTY_SET_REPLY, TopicDirection.UPLINK),
    "drc/up": (TopicKind.DRC_UP, TopicDirection.UPLINK),
    "drc/down": (TopicKind.DRC_DOWN, TopicDirection.DOWNLINK),
}


def parse_topic(topic: str) -> ParsedTopic:
    parts = topic.split("/")

    if len(parts) == 4 and parts[0] == "sys" and parts[1] == "product":
        gateway_sn = parts[2] or None
        if parts[3] == "status":
            return ParsedTopic(
                topic,
                gateway_sn,
                TopicKind.STATUS,
                TopicDirection.UPLINK,
            )
        if parts[3] == "status_reply":
            return ParsedTopic(
                topic,
                gateway_sn,
                TopicKind.STATUS_REPLY,
                TopicDirection.DOWNLINK,
            )

    if len(parts) >= 4 and parts[0] == "thing" and parts[1] == "product":
        device_sn = parts[2] or None
        suffix = "/".join(parts[3:])
        kind, direction = _THING_SUFFIXES.get(
            suffix,
            (TopicKind.UNKNOWN, None),
        )
        return ParsedTopic(topic, device_sn, kind, direction)

    return ParsedTopic(topic, None, TopicKind.UNKNOWN, None)


def status_reply_topic(gateway_sn: str) -> str:
    return f"sys/product/{gateway_sn}/status_reply"


def state_reply_topic(device_sn: str) -> str:
    return f"thing/product/{device_sn}/state_reply"


def services_topic(gateway_sn: str) -> str:
    return f"thing/product/{gateway_sn}/services"


def events_reply_topic(gateway_sn: str) -> str:
    return f"thing/product/{gateway_sn}/events_reply"


def requests_reply_topic(gateway_sn: str) -> str:
    return f"thing/product/{gateway_sn}/requests_reply"


def property_set_topic(gateway_sn: str) -> str:
    return f"thing/product/{gateway_sn}/property/set"


def drc_down_topic(gateway_sn: str) -> str:
    return f"thing/product/{gateway_sn}/drc/down"
