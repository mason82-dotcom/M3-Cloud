from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
from redis.asyncio import Redis

from app.config import settings
from app.vehicles.lyrebird import (
    merge_dicts,
    merge_identity_config,
    merge_transport_telemetry,
    normalize_config,
    normalize_telemetry,
)
from app.vehicles.base import VehicleSnapshot
from app.vehicles.mavlink import LyrebirdMavlinkCollector


class VehicleTelemetryObserver:
    async def ingest_vehicle(self, vehicle: VehicleSnapshot) -> None:
        ...

class LyrebirdLiveBridge:
    """Publish Lyrebird MAVLink immediately and enrich it with the persistent TCP stream."""

    def __init__(
        self,
        redis: Redis,
        collector: LyrebirdMavlinkCollector,
        telemetry_observer: VehicleTelemetryObserver | None = None,
    ):
        self.redis = redis
        self.collector = collector
        self.telemetry_observer = telemetry_observer
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._tcp: dict[str, dict[str, Any]] = {}
        self._config: dict[str, dict[str, Any]] = {}
        self._camera_caps: dict[str, dict[str, Any]] = {}
        self._tcp_seen: dict[str, float] = {}
        self._http_seen: dict[str, float] = {}
        self._identity_attempted_at: dict[str, float] = {}

    async def start(self) -> None:
        if not settings.lyrebird_enabled:
            return
        self.collector.set_publisher(self.publish_mavlink)
        for host in [x.strip() for x in settings.lyrebird_hosts.split(",") if x.strip()]:
            self._tasks[host] = asyncio.create_task(self._tcp_loop(host), name=f"lyrebird-tcp-{host}")

    async def stop(self) -> None:
        self.collector.set_publisher(None)
        tasks = tuple(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _identity(self, host: str) -> tuple[dict[str, Any], dict[str, Any]]:
        now = time.monotonic()
        cached_config = self._config.get(host)
        cached_caps = self._camera_caps.get(host)
        # A complete identity can be reused. If camera identity was missing during
        # startup, retry periodically instead of freezing UNKNOWN for the process lifetime.
        if cached_config is not None and cached_caps:
            return cached_config, cached_caps
        last_attempt = self._identity_attempted_at.get(host)
        if cached_config is not None and last_attempt is not None and now - last_attempt < 5.0:
            return cached_config, cached_caps or {}

        self._identity_attempted_at[host] = now
        async with httpx.AsyncClient() as client:
            config = cached_config or {}
            camera = cached_caps or {}
            identity_settings: dict[str, Any] = {}
            try:
                # Keep RC HTTP requests sequential; the embedded server may serialize
                # requests and concurrent probes can otherwise lose camera identity.
                if not config:
                    cfg = await client.get(
                        f"http://{host}:{settings.lyrebird_http_port}/config",
                        timeout=settings.lyrebird_timeout_seconds,
                        headers={"Connection": "close"},
                    )
                    if cfg.is_success:
                        value = cfg.json()
                        if isinstance(value, dict):
                            config = value

                caps = await client.get(
                    f"http://{host}:{settings.lyrebird_http_port}/get/camera/capabilities",
                    timeout=settings.lyrebird_timeout_seconds,
                    headers={"Connection": "close"},
                )
                if caps.is_success:
                    value = caps.json()
                    if isinstance(value, dict) and value:
                        camera = value

                identity = await client.get(
                    f"http://{host}:{settings.lyrebird_http_port}/config/settings",
                    timeout=settings.lyrebird_timeout_seconds,
                    headers={"Connection": "close"},
                )
                if identity.is_success:
                    value = identity.json()
                    if isinstance(value, dict):
                        identity_settings = value
            except (httpx.HTTPError, ValueError):
                pass

            if isinstance(config, dict) and config:
                config = merge_identity_config(config, identity_settings)
                self._config[host] = config
                self._http_seen[host] = time.monotonic()
            if isinstance(camera, dict) and camera:
                self._camera_caps[host] = camera

        return self._config.get(host, {"droneName": host}), self._camera_caps.get(host, {})

    def health(self) -> dict[str, Any]:
        now = time.monotonic()
        hosts: dict[str, Any] = {}
        states: list[str] = []
        for host in [x.strip() for x in settings.lyrebird_hosts.split(",") if x.strip()]:
            mav = self.collector.snapshot(host)
            tcp_age = now - self._tcp_seen[host] if host in self._tcp_seen else None
            http_age = now - self._http_seen[host] if host in self._http_seen else None
            mav_ok = mav is not None
            tcp_ok = tcp_age is not None and tcp_age <= settings.lyrebird_mavlink_ttl_seconds
            http_ok = http_age is not None and http_age <= 30.0
            if mav_ok and tcp_ok: status = "ONLINE"
            elif mav_ok or tcp_ok: status = "DEGRADED"
            elif http_ok: status = "STALE"
            else: status = "OFFLINE"
            states.append(status)
            hosts[host] = {"status": status, "mavlink": mav_ok, "tcp": tcp_ok, "http": http_ok, "tcp_mode": "gap"}
        overall = "OFFLINE"
        for candidate in ("ONLINE", "DEGRADED", "STALE"):
            if candidate in states:
                overall = candidate
                break
        return {"ok": overall in {"ONLINE", "DEGRADED"}, "status": overall, "hosts": hosts}

    async def _publish(self, host: str, telemetry: dict[str, Any]) -> None:
        config, caps = await self._identity(host)
        vehicle = normalize_config(host, config, telemetry, caps)
        if self.telemetry_observer is not None:
            await self.telemetry_observer.ingest_vehicle(vehicle)
        await self.redis.publish(settings.live_redis_channel, json.dumps({
            "type": "vehicle_telemetry",
            "vehicle_id": vehicle.id,
            "device_sn": vehicle.sn,
            "source": "lyrebird",
            "vehicle": vehicle.as_dict(),
        }))

    async def publish_mavlink(self, host: str, mavlink: dict[str, Any]) -> None:
        await self._publish(host, merge_transport_telemetry(mavlink, self._tcp.get(host)) or mavlink)

    async def _tcp_loop(self, host: str) -> None:
        while True:
            writer = None
            try:
                reader, writer = await asyncio.open_connection(host, settings.lyrebird_telemetry_port)
                # Match Lyrebird Transport.BOTH: MAVLink owns standard telemetry, TCP sends only gaps.
                # Older aircraft safely ignore this unknown request and continue with full snapshots.
                writer.write(b"MODE=GAP\n")
                await writer.drain()
                while True:
                    line = await reader.readline()
                    if not line:
                        raise ConnectionError("Lyrebird telemetry stream closed")
                    raw = json.loads(line.decode("utf-8"))
                    if not isinstance(raw, dict):
                        continue
                    current = normalize_telemetry(raw)
                    if raw.get("telemetryMode") == "gap" and host in self._tcp:
                        # GAP payloads are partial by definition. Nulls from absent normalized
                        # fields must not erase the last valid TCP value.
                        current = merge_dicts(self._tcp[host], current, ignore_none=True)
                    self._tcp[host] = current
                    self._tcp_seen[host] = time.monotonic()
                    mavlink = self.collector.snapshot(host)
                    await self._publish(host, merge_transport_telemetry(mavlink, current) or current)
            except (OSError, ConnectionError, UnicodeDecodeError, json.JSONDecodeError):
                await asyncio.sleep(1.0)
            finally:
                if writer is not None:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError:
                        pass
