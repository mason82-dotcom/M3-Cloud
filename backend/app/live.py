from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis


logger = logging.getLogger(__name__)

router = APIRouter(tags=["live"])


class LiveTelemetryHub:
    """Fan Redis Pub/Sub events out to WebSockets owned by this backend worker."""

    def __init__(
        self,
        redis: Redis,
        *,
        channel: str = "m3:live",
        reconnect_delay_s: float = 1.0,
        send_timeout_s: float = 1.0,
    ):
        self.redis = redis
        self.channel = channel
        self.reconnect_delay_s = reconnect_delay_s
        self.send_timeout_s = max(0.05, float(send_timeout_s))
        self.connections: set[WebSocket] = set()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._subscriber_loop(),
                name="m3-live-redis-subscriber",
            )

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)
        await websocket.send_json(
            {
                "type": "connected",
                "channel": "telemetry",
            }
        )

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def _send(self, websocket: WebSocket, event: dict[str, Any]) -> bool:
        try:
            await asyncio.wait_for(
                websocket.send_json(event),
                timeout=self.send_timeout_s,
            )
            return True
        except Exception:
            return False

    async def broadcast(self, event: dict[str, Any]) -> None:
        sockets = tuple(self.connections)
        if not sockets:
            return

        results = await asyncio.gather(
            *(self._send(websocket, event) for websocket in sockets)
        )
        for websocket, ok in zip(sockets, results, strict=True):
            if not ok:
                self.disconnect(websocket)

    async def _subscriber_loop(self) -> None:
        while True:
            pubsub = self.redis.pubsub()
            try:
                await pubsub.subscribe(self.channel)
                logger.info("Live telemetry subscribed to Redis channel %s", self.channel)

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
                        logger.warning("Ignoring malformed live event")
                        continue

                    if isinstance(event, dict):
                        await self.broadcast(event)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Redis live-event subscription failed; retrying in %.1fs",
                    self.reconnect_delay_s,
                )
                await asyncio.sleep(self.reconnect_delay_s)
            finally:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()


@router.websocket("/ws/live")
async def live_telemetry(websocket: WebSocket) -> None:
    hub: LiveTelemetryHub = websocket.app.state.live_hub
    await hub.connect(websocket)

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(websocket)
