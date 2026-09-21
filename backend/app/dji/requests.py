from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.dji.protocol import Envelope


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DJIRequestResponse:
    result: int
    output: dict[str, Any] | None = None


RequestHandler = Callable[[str, Envelope], Awaitable[DJIRequestResponse]]


class DJIRequestDispatcher:
    """Dispatch Device -> Cloud requests to explicit method handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, RequestHandler] = {}

    def register(self, method: str, handler: RequestHandler) -> None:
        if not method:
            raise ValueError("DJI request method cannot be empty")
        self._handlers[method] = handler

    async def handle(
        self,
        gateway_sn: str,
        envelope: Envelope,
    ) -> DJIRequestResponse:
        handler = self._handlers.get(envelope.method)
        if handler is None:
            logger.warning(
                "No DJI request handler registered for %s from %s",
                envelope.method,
                gateway_sn,
            )
            # A non-zero result is deliberate: never claim success when the
            # requested server-side capability has not been implemented.
            return DJIRequestResponse(result=1)

        return await handler(gateway_sn, envelope)
