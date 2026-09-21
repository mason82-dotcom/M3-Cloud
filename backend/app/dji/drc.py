from __future__ import annotations

import json
import time
from copy import deepcopy
from typing import Any

from redis.asyncio import Redis

from app.config import settings
from app.dji.protocol import DRCMessage


class DJIDRCStateStore:
    """Cache DJI DRC uplink state without interpreting it as flight authority."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def latest_key(gateway_sn: str, method: str) -> str:
        return f"dji:drc:{gateway_sn}:{method}"

    async def update(
        self,
        gateway_sn: str,
        message: DRCMessage,
    ) -> dict[str, Any]:
        received_at_ms = int(time.time() * 1000)
        record = {
            "gateway_sn": gateway_sn,
            "method": message.method,
            "seq": message.seq,
            "timestamp": message.timestamp,
            "received_at_ms": received_at_ms,
            "data": deepcopy(message.data),
        }
        encoded = json.dumps(
            record,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        await self.redis.set(
            self.latest_key(gateway_sn, message.method),
            encoded,
            ex=settings.dji_telemetry_ttl_seconds,
        )
        await self.redis.publish(
            settings.live_redis_channel,
            json.dumps(
                {
                    "type": "dji_drc",
                    "device_sn": gateway_sn,
                    "timestamp": received_at_ms,
                    "drc": record,
                },
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        )
        return record

    async def get_latest(
        self,
        gateway_sn: str,
        method: str,
    ) -> dict[str, Any] | None:
        raw = await self.redis.get(self.latest_key(gateway_sn, method))
        return json.loads(raw) if raw else None
