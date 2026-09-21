from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Protocol

from redis.asyncio import Redis

from app.config import settings
from app.dji.protocol import DRCMessage, encode_json
from app.dji.topics import drc_down_topic


logger = logging.getLogger(__name__)


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



class DRCPublisher(Protocol):
    async def publish(
        self,
        topic: str,
        payload: bytes,
        *,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        ...


class DJIDRCCommandChannel:
    """Publish sequence-numbered DJI DRC packets on the gateway downlink."""

    def __init__(self, publisher: DRCPublisher) -> None:
        self.publisher = publisher
        self._sequences: dict[str, int] = {}

    def _next_sequence(self, gateway_sn: str) -> int:
        value = self._sequences.get(gateway_sn, 0) + 1
        self._sequences[gateway_sn] = value
        return value

    async def send(
        self,
        gateway_sn: str,
        method: str,
        data: Mapping[str, Any] | None = None,
    ) -> int:
        if not method:
            raise ValueError("DJI DRC method cannot be empty")
        seq = self._next_sequence(gateway_sn)
        await self.publisher.publish(
            drc_down_topic(gateway_sn),
            encode_json(
                {
                    "method": method,
                    "seq": seq,
                    "data": dict(data or {}),
                }
            ),
            qos=0,
            retain=False,
        )
        return seq


class DJIDRCSessionManager:
    """Keep a DRC link alive after Pilot accepts drc_mode_enter."""

    def __init__(
        self,
        channel: DJIDRCCommandChannel,
        *,
        heartbeat_interval_s: float,
    ) -> None:
        self.channel = channel
        self.heartbeat_interval_s = max(0.1, float(heartbeat_interval_s))
        self._tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def active_gateways(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                gateway_sn
                for gateway_sn, task in self._tasks.items()
                if not task.done()
            )
        )

    async def start(self, gateway_sn: str) -> None:
        current = self._tasks.get(gateway_sn)
        if current is not None and not current.done():
            return

        # DJI documents this as the first DRC/down request for obtaining the
        # current aircraft/camera state after the link is established.
        await self.channel.send(
            gateway_sn,
            "drc_initial_state_subscribe",
            {},
        )
        task = asyncio.create_task(
            self._heartbeat_loop(gateway_sn),
            name=f"dji-drc-heartbeat-{gateway_sn}",
        )
        self._tasks[gateway_sn] = task

    async def stop(self, gateway_sn: str) -> None:
        task = self._tasks.pop(gateway_sn, None)
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def stop_all(self) -> None:
        for gateway_sn in tuple(self._tasks):
            await self.stop(gateway_sn)

    async def _heartbeat_loop(self, gateway_sn: str) -> None:
        try:
            while True:
                await self.channel.send(
                    gateway_sn,
                    "heart_beat",
                    {"timestamp": int(time.time() * 1000)},
                )
                await asyncio.sleep(self.heartbeat_interval_s)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "DJI DRC heartbeat failed for %s; stopping session",
                gateway_sn,
            )
        finally:
            current = self._tasks.get(gateway_sn)
            if current is asyncio.current_task():
                self._tasks.pop(gateway_sn, None)
