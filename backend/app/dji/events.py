from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any

from redis.asyncio import Redis

from app.config import settings
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



class DJIEventStateStore:
    """Persist documented RC Pro Enterprise events and mirror them to live consumers."""

    AUTH_METHOD = "cloud_control_auth_notify"
    DRC_METHOD = "drc_status_notify"
    PHOTO_METHOD = "camera_photo_take_progress"

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def latest_key(gateway_sn: str, method: str) -> str:
        return f"dji:event:{gateway_sn}:{method}"

    @staticmethod
    def photo_key(gateway_sn: str, bid: str) -> str:
        return f"dji:event:{gateway_sn}:camera_photo_take_progress:{bid}"

    @staticmethod
    def _record(gateway_sn: str, envelope: Envelope) -> dict[str, Any]:
        return {
            "gateway_sn": gateway_sn,
            "tid": envelope.tid,
            "bid": envelope.bid,
            "timestamp": envelope.timestamp,
            "method": envelope.method,
            "need_reply": envelope.need_reply,
            "data": deepcopy(envelope.data),
        }

    async def _persist(
        self,
        gateway_sn: str,
        envelope: Envelope,
        *,
        extra_key: str | None = None,
    ) -> None:
        record = self._record(gateway_sn, envelope)
        encoded = json.dumps(record, separators=(",", ":"), ensure_ascii=False)
        await self.redis.set(
            self.latest_key(gateway_sn, envelope.method),
            encoded,
            ex=settings.dji_state_cache_ttl_seconds,
        )
        if extra_key is not None:
            await self.redis.set(
                extra_key,
                encoded,
                ex=settings.dji_state_cache_ttl_seconds,
            )
        await self.redis.publish(
            settings.live_redis_channel,
            json.dumps(
                {
                    "type": "dji_event",
                    "device_sn": gateway_sn,
                    "timestamp": envelope.timestamp,
                    "event": record,
                },
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        )

    async def cloud_control_auth_notify(
        self,
        gateway_sn: str,
        envelope: Envelope,
    ) -> int:
        result = envelope.data.get("result")
        output = envelope.data.get("output")
        status_value = output.get("status") if isinstance(output, dict) else None
        if (
            not isinstance(result, int)
            or isinstance(result, bool)
            or status_value not in {"canceled", "failed", "ok"}
        ):
            logger.warning(
                "Invalid DJI cloud_control_auth_notify from %s",
                gateway_sn,
            )
            return 1

        await self._persist(gateway_sn, envelope)
        return 0

    async def drc_status_notify(
        self,
        gateway_sn: str,
        envelope: Envelope,
    ) -> int:
        result = envelope.data.get("result")
        drc_state = envelope.data.get("drc_state")
        if (
            not isinstance(result, int)
            or isinstance(result, bool)
            or not isinstance(drc_state, int)
            or isinstance(drc_state, bool)
            or drc_state not in (0, 1, 2)
        ):
            logger.warning("Invalid DJI drc_status_notify from %s", gateway_sn)
            return 1

        await self._persist(gateway_sn, envelope)
        return 0

    async def camera_photo_take_progress(
        self,
        gateway_sn: str,
        envelope: Envelope,
    ) -> int:
        result = envelope.data.get("result")
        output = envelope.data.get("output")
        if (
            not isinstance(result, int)
            or isinstance(result, bool)
            or not isinstance(output, dict)
        ):
            logger.warning(
                "Invalid DJI camera_photo_take_progress from %s",
                gateway_sn,
            )
            return 1

        status_value = output.get("status")
        if status_value not in {"fail", "in_progress", "ok"}:
            return 1

        progress = output.get("progress")
        if progress is not None:
            if not isinstance(progress, dict):
                return 1
            percent = progress.get("percent")
            current_step = progress.get("current_step")
            if (
                not isinstance(percent, int)
                or isinstance(percent, bool)
                or not 0 <= percent <= 100
                or not isinstance(current_step, int)
                or isinstance(current_step, bool)
            ):
                return 1

        await self._persist(
            gateway_sn,
            envelope,
            extra_key=self.photo_key(gateway_sn, envelope.bid),
        )
        return 0

    async def get_latest(
        self,
        gateway_sn: str,
        method: str,
    ) -> dict[str, Any] | None:
        raw = await self.redis.get(self.latest_key(gateway_sn, method))
        return json.loads(raw) if raw else None

    async def get_photo_progress(
        self,
        gateway_sn: str,
        bid: str,
    ) -> dict[str, Any] | None:
        raw = await self.redis.get(self.photo_key(gateway_sn, bid))
        return json.loads(raw) if raw else None

    def register(self, dispatcher: DJIEventDispatcher) -> None:
        dispatcher.register(self.AUTH_METHOD, self.cloud_control_auth_notify)
        dispatcher.register(self.DRC_METHOD, self.drc_status_notify)
        dispatcher.register(self.PHOTO_METHOD, self.camera_photo_take_progress)
