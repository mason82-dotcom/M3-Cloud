from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TopicKind(StrEnum):
    STATUS = "status"
    STATUS_REPLY = "status_reply"
    OSD = "osd"
    STATE = "state"
    EVENTS = "events"
    EVENTS_REPLY = "events_reply"
    REQUESTS = "requests"
    REQUESTS_REPLY = "requests_reply"
    SERVICES = "services"
    SERVICES_REPLY = "services_reply"
    PROPERTY_SET = "property_set"
    PROPERTY_SET_REPLY = "property_set_reply"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ParsedTopic:
    raw: str
    device_sn: str | None
    kind: TopicKind

    @property
    def gateway_sn(self) -> str | None:
        """Compatibility alias: status topics use the device SN as gateway SN."""

        return self.device_sn


SUBSCRIPTIONS: tuple[str, ...] = (
    "sys/product/+/status",
    "thing/product/+/osd",
    "thing/product/+/state",
    "thing/product/+/events",
    "thing/product/+/events_reply",
    "thing/product/+/requests",
    "thing/product/+/requests_reply",
    "thing/product/+/services",
    "thing/product/+/services_reply",
    "thing/product/+/property/set",
    "thing/product/+/property/set_reply",
)


_THING_SUFFIXES = {
    "osd": TopicKind.OSD,
    "state": TopicKind.STATE,
    "events": TopicKind.EVENTS,
    "events_reply": TopicKind.EVENTS_REPLY,
    "requests": TopicKind.REQUESTS,
    "requests_reply": TopicKind.REQUESTS_REPLY,
    "services": TopicKind.SERVICES,
    "services_reply": TopicKind.SERVICES_REPLY,
    "property/set": TopicKind.PROPERTY_SET,
    "property/set_reply": TopicKind.PROPERTY_SET_REPLY,
}


def parse_topic(topic: str) -> ParsedTopic:
    parts = topic.split("/")

    if len(parts) == 4 and parts[0] == "sys" and parts[1] == "product":
        gateway_sn = parts[2] or None
        if parts[3] == "status":
            return ParsedTopic(topic, gateway_sn, TopicKind.STATUS)
        if parts[3] == "status_reply":
            return ParsedTopic(topic, gateway_sn, TopicKind.STATUS_REPLY)

    if len(parts) >= 4 and parts[0] == "thing" and parts[1] == "product":
        gateway_sn = parts[2] or None
        suffix = "/".join(parts[3:])
        return ParsedTopic(
            topic,
            gateway_sn,
            _THING_SUFFIXES.get(suffix, TopicKind.UNKNOWN),
        )

    return ParsedTopic(topic, None, TopicKind.UNKNOWN)


def status_reply_topic(gateway_sn: str) -> str:
    return f"sys/product/{gateway_sn}/status_reply"
