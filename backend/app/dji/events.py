from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.dji.protocol import Envelope


logger = logging.getLogger(__name__)

EventHandler = Callable[[str, Envelope], Awaitable[int | None]]


class DJIEventDispatcher:
    """Dispatch Device -> Cloud events while allowing unknown notifications to be acknowledged."""

    def __init__(self) -> None:
        self._handlers: dict[str, EventHandler] = {}

    def register(self, method: str, handler: EventHandler) -> None:
        if not method:
            raise ValueError("DJI event method cannot be empty")
        self._handlers[method] = handler

    async def handle(self, gateway_sn: str, envelope: Envelope) -> int:
        handler = self._handlers.get(envelope.method)
        if handler is None:
            logger.info(
                "No DJI event handler registered for %s from %s",
                envelope.method,
                gateway_sn,
            )
            return 0

        result = await handler(gateway_sn, envelope)
        return 0 if result is None else int(result)
