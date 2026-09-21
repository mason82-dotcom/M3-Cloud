from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from fastapi import WebSocket
from redis.asyncio import Redis

from app.dji.tsa import live_event_to_pilot


logger = logging.getLogger(__name__)


class DJIPilotWebSocketHub:
    """Translate M3-Cloud DJI live events into DJI Pilot 2 WS messages."""

    def __init__(
        self,
        redis: Redis,
        *,
        channel: str,
        reconnect_delay_s: float = 1.0,
    ) -> None:
        self.redis = redis
        self.channel = channel
        self.reconnect_delay_s = reconnect_delay_s
        self.connections: set[WebSocket] = set()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._subscriber_loop(),
                name="dji-pilot-ws-subscriber",
            )

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        for websocket in tuple(self.connections):
            with contextlib.suppress(Exception):
                await websocket.close(code=1001)
        self.connections.clear()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for websocket in tuple(self.connections):
            try:
                await websocket.send_json(payload)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket)

    async def _subscriber_loop(self) -> None:
        while True:
            pubsub = self.redis.pubsub()
            try:
                await pubsub.subscribe(self.channel)
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue

                    raw = message.get("data")
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    if not isinstance(raw, str):
                        continue

                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue

                    translated = live_event_to_pilot(event)
                    if translated is not None:
                        await self.broadcast(translated)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "DJI Pilot WS Redis subscription failed; retrying in %.1fs",
                    self.reconnect_delay_s,
                )
                await asyncio.sleep(self.reconnect_delay_s)
            finally:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()
