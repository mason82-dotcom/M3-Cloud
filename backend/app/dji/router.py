from __future__ import annotations

import logging
from typing import Protocol

from app.dji.protocol import (
    ProtocolError,
    encode_json,
    make_property_reply,
    make_reply,
    parse_envelope,
    parse_property_message,
)
from app.dji.registry import DeviceRegistry
from app.dji.telemetry import TelemetryStore
from app.dji.topics import TopicKind, parse_topic, state_reply_topic, status_reply_topic


logger = logging.getLogger(__name__)


class Publisher(Protocol):
    async def publish(self, topic: str, payload: bytes, *, qos: int = 0, retain: bool = False) -> None:
        ...


class DJIMessageRouter:
    def __init__(
        self,
        registry: DeviceRegistry,
        publisher: Publisher,
        telemetry: TelemetryStore,
    ):
        self.registry = registry
        self.publisher = publisher
        self.telemetry = telemetry

    async def handle(self, topic: str, payload: bytes, *, qos: int = 0, retain: bool = False) -> None:
        del qos, retain
        parsed = parse_topic(topic)
        if not parsed.device_sn:
            return

        if parsed.kind in (TopicKind.OSD, TopicKind.STATE):
            try:
                message = parse_property_message(payload)
                await self.telemetry.update(
                    source_sn=parsed.device_sn,
                    kind=parsed.kind,
                    message=message,
                )
                if parsed.kind is TopicKind.STATE and message.need_reply:
                    await self.publisher.publish(
                        state_reply_topic(parsed.device_sn),
                        encode_json(make_property_reply(message, result=0)),
                        qos=0,
                        retain=False,
                    )
            except (ProtocolError, ValueError):
                logger.warning("Ignoring invalid DJI property payload on %s", topic, exc_info=True)
            except Exception:
                logger.exception("Failed to store DJI telemetry for %s", parsed.device_sn)
            return

        if parsed.kind is not TopicKind.STATUS:
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
            await self.registry.update_topology(parsed.device_sn, envelope)
        except Exception:
            logger.exception("Failed to update DJI topology for %s", parsed.device_sn)
            return

        reply = make_reply(envelope, result=0)
        await self.publisher.publish(
            status_reply_topic(parsed.device_sn),
            encode_json(reply),
            qos=0,
            retain=False,
        )
