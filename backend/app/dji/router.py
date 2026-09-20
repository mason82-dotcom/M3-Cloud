from __future__ import annotations

import logging
from typing import Protocol

from app.dji.protocol import ProtocolError, encode_json, make_reply, parse_envelope
from app.dji.registry import DeviceRegistry
from app.dji.topics import TopicKind, parse_topic, status_reply_topic


logger = logging.getLogger(__name__)


class Publisher(Protocol):
    async def publish(self, topic: str, payload: bytes, *, qos: int = 0, retain: bool = False) -> None:
        ...


class DJIMessageRouter:
    def __init__(self, registry: DeviceRegistry, publisher: Publisher):
        self.registry = registry
        self.publisher = publisher

    async def handle(self, topic: str, payload: bytes, *, qos: int = 0, retain: bool = False) -> None:
        del qos, retain
        parsed = parse_topic(topic)
        if parsed.kind is not TopicKind.STATUS or not parsed.gateway_sn:
            return

        try:
            envelope = parse_envelope(payload)
        except ProtocolError:
            logger.warning("Ignoring invalid DJI status payload on %s", topic, exc_info=True)
            return

        if envelope.method != "update_topo":
            logger.info("Ignoring unsupported DJI status method %s", envelope.method)
            return

        try:
            await self.registry.update_topology(parsed.gateway_sn, envelope)
        except Exception:
            logger.exception("Failed to update DJI topology for %s", parsed.gateway_sn)
            return

        reply = make_reply(envelope, result=0)
        await self.publisher.publish(
            status_reply_topic(parsed.gateway_sn),
            encode_json(reply),
            qos=0,
            retain=False,
        )
