from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.config import settings
from app.vehicles.base import VehicleSnapshot


def _configured_hosts() -> list[str]:
    return [item.strip() for item in settings.lyrebird_hosts.split(",") if item.strip()]


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) else None


def normalize_config(host: str, config: dict[str, Any]) -> VehicleSnapshot:
    """Normalize Lyrebird's documented GET /config snapshot.

    /config is intentionally used for discovery/identity only. Flight state remains on
    Lyrebird's TCP/MAVLink telemetry channels and is not guessed from configuration fields.
    """
    name = str(config.get("droneName") or config.get("name") or host)
    model = str(config.get("aircraftModel") or config.get("productName") or "LYREBIRD_AIRCRAFT")
    serial = str(config.get("aircraftSerialNumber") or config.get("serialNumber") or host)
    now = int(time.time() * 1000)
    return VehicleSnapshot(
        id=f"lyrebird:{serial}",
        sn=serial,
        name=name,
        model=model,
        source="lyrebird",
        online=True,
        updated_at_ms=now,
        telemetry=None,
    )


class LyrebirdVehicleProvider:
    """Read Lyrebird identity through its existing public HTTP surface.

    Hosts are explicit configuration for the server deployment. We deliberately do not run
    Lyrebird's UDP subnet discovery inside the web API process: container broadcast behaviour
    is deployment-specific, while the canonical Lyrebird discovery implementation remains in
    GroundStation/Python.
    """

    source = "lyrebird"

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client

    async def _probe(self, client: httpx.AsyncClient, host: str) -> VehicleSnapshot | None:
        try:
            response = await client.get(
                f"http://{host}:{settings.lyrebird_http_port}/config",
                timeout=settings.lyrebird_timeout_seconds,
            )
            response.raise_for_status()
            config = response.json()
            if not isinstance(config, dict):
                return None
            return normalize_config(host, config)
        except (httpx.HTTPError, ValueError):
            return None

    async def list_vehicles(self) -> list[VehicleSnapshot]:
        if not settings.lyrebird_enabled:
            return []
        hosts = _configured_hosts()
        if not hosts:
            return []
        if self._client is not None:
            results = await asyncio.gather(*(self._probe(self._client, host) for host in hosts))
        else:
            async with httpx.AsyncClient() as client:
                results = await asyncio.gather(*(self._probe(client, host) for host in hosts))
        return [item for item in results if item is not None]
