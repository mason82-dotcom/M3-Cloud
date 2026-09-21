from __future__ import annotations

import logging
from typing import Protocol

from app.dji.events import DJIEventDispatcher
from app.dji.protocol import (
    ProtocolError,
    encode_json,
    make_property_reply,
    make_reply,
    parse_correlated_message,
    parse_envelope,
    parse_property_message,
)
from app.dji.registry import DeviceRegistry
from app.dji.requests import DJIRequestDispatcher
from app.dji.telemetry import TelemetryStore
from app.dji.topics import (
    TopicKind,
    events_reply_topic,
    parse_topic,
    requests_reply_topic,
    state_reply_topic,
    status_reply_topic,
)
from app.dji.transactions import DJITransactionManager


logger = logging.getLogger(__name__)


class Publisher(Protocol):
    async def publish(
        self,
        topic: str,
        payload: bytes,
        *,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        ...


class DJIMessageRouter:
    def __init__(
        self,
        registry: DeviceRegistry,
        publisher: Publisher,
        telemetry: TelemetryStore,
        *,
        transactions: DJITransactionManager | None = None,
        events: DJIEventDispatcher | None = None,
        requests: DJIRequestDispatcher | None = None,
    ):
        self.registry = registry
        self.publisher = publisher
        self.telemetry = telemetry
        self.transactions = transactions
        self.events = events
        self.requests = requests

    async def handle(
        self,
        topic: str,
        payload: bytes,
        *,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        del qos, retain
        parsed = parse_topic(topic)
        if not parsed.device_sn:
            return

        if parsed.kind in (TopicKind.OSD, TopicKind.STATE):
            await self._handle_property_stream(parsed.device_sn, parsed.kind, payload)
            return

        if parsed.kind is TopicKind.STATUS:
            await self._handle_status(parsed.device_sn, payload)
            return

        if parsed.kind is TopicKind.SERVICES_REPLY:
            await self._handle_service_reply(parsed.device_sn, payload)
            return

        if parsed.kind is TopicKind.PROPERTY_SET_REPLY:
            await self._handle_property_set_reply(parsed.device_sn, payload)
            return

        if parsed.kind is TopicKind.EVENTS:
            await self._handle_event(parsed.device_sn, payload)
            return

        if parsed.kind is TopicKind.REQUESTS:
            await self._handle_request(parsed.device_sn, payload)
            return

        if parsed.kind is TopicKind.DRC_UP:
            logger.debug("DJI DRC uplink received from %s", parsed.device_sn)
            return

        logger.debug("Ignoring unsupported DJI topic %s", topic)

    async def _handle_property_stream(
        self,
        device_sn: str,
        kind: TopicKind,
        payload: bytes,
    ) -> None:
        try:
            message = parse_property_message(payload)
            await self.telemetry.update(
                source_sn=device_sn,
                kind=kind,
                message=message,
            )
            if kind is TopicKind.STATE and message.need_reply:
                await self.publisher.publish(
                    state_reply_topic(device_sn),
                    encode_json(make_property_reply(message, result=0)),
                    qos=0,
                    retain=False,
                )
        except (ProtocolError, ValueError):
            logger.warning(
                "Ignoring invalid DJI property payload for %s",
                device_sn,
                exc_info=True,
            )
        except Exception:
            logger.exception("Failed to store DJI telemetry for %s", device_sn)

    async def _handle_status(self, gateway_sn: str, payload: bytes) -> None:
        try:
            envelope = parse_envelope(payload)
        except ProtocolError:
            logger.warning(
                "Ignoring invalid DJI status payload for %s",
                gateway_sn,
                exc_info=True,
            )
            return

        if envelope.method != "update_topo":
            logger.info("Ignoring unsupported DJI status method %s", envelope.method)
            return

        try:
            await self.registry.update_topology(gateway_sn, envelope)
        except Exception:
            logger.exception("Failed to update DJI topology for %s", gateway_sn)
            return

        await self.publisher.publish(
            status_reply_topic(gateway_sn),
            encode_json(make_reply(envelope, result=0)),
            qos=0,
            retain=False,
        )

    async def _handle_service_reply(self, gateway_sn: str, payload: bytes) -> None:
        try:
            envelope = parse_envelope(payload)
        except ProtocolError:
            logger.warning(
                "Ignoring invalid DJI services_reply from %s",
                gateway_sn,
                exc_info=True,
            )
            return

        if (
            self.transactions is not None
            and self.transactions.resolve(
                TopicKind.SERVICES_REPLY,
                gateway_sn,
                envelope.tid,
                envelope,
            )
        ):
            return

        logger.warning(
            "Unmatched DJI services_reply %s/%s from %s",
            envelope.method,
            envelope.tid,
            gateway_sn,
        )

    async def _handle_property_set_reply(
        self,
        gateway_sn: str,
        payload: bytes,
    ) -> None:
        try:
            message = parse_correlated_message(payload)
        except ProtocolError:
            logger.warning(
                "Ignoring invalid DJI property/set_reply from %s",
                gateway_sn,
                exc_info=True,
            )
            return

        if (
            self.transactions is not None
            and self.transactions.resolve(
                TopicKind.PROPERTY_SET_REPLY,
                gateway_sn,
                message.tid,
                message,
            )
        ):
            return

        logger.warning(
            "Unmatched DJI property/set_reply %s from %s",
            message.tid,
            gateway_sn,
        )

    async def _handle_event(self, gateway_sn: str, payload: bytes) -> None:
        try:
            envelope = parse_envelope(payload)
        except ProtocolError:
            logger.warning(
                "Ignoring invalid DJI event from %s",
                gateway_sn,
                exc_info=True,
            )
            return

        result = (
            await self.events.handle(gateway_sn, envelope)
            if self.events is not None
            else 0
        )
        if envelope.need_reply:
            await self.publisher.publish(
                events_reply_topic(gateway_sn),
                encode_json(make_reply(envelope, result=result)),
                qos=0,
                retain=False,
            )

    async def _handle_request(self, gateway_sn: str, payload: bytes) -> None:
        try:
            envelope = parse_envelope(payload)
        except ProtocolError:
            logger.warning(
                "Ignoring invalid DJI request from %s",
                gateway_sn,
                exc_info=True,
            )
            return

        if self.requests is None:
            result = 1
            output = None
        else:
            response = await self.requests.handle(gateway_sn, envelope)
            result = response.result
            output = response.output

        await self.publisher.publish(
            requests_reply_topic(gateway_sn),
            encode_json(
                make_reply(
                    envelope,
                    result=result,
                    output=output,
                )
            ),
            qos=0,
            retain=False,
        )
