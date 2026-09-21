from __future__ import annotations

import time
from typing import Any, Mapping

from redis.asyncio import Redis

from app.config import settings
from app.dji.registry import DeviceRegistry
from app.dji.telemetry import TelemetryStore
from app.vehicles.base import VehicleSnapshot, canonical_vehicle_id
from app.vehicles.state import normalize_aircraft_state


def _numeric_ms(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _device_online(
    device: Mapping[str, Any],
    state: Mapping[str, Any] | None,
    *,
    now_ms: int | None = None,
) -> bool:
    """Require fresh DJI telemetry, with a short grace after topology discovery."""

    if device.get("online") is not True:
        return False

    now = now_ms if now_ms is not None else int(time.time() * 1000)
    ttl_ms = max(1, int(settings.dji_telemetry_ttl_seconds)) * 1000

    if state is not None:
        last_seen = _numeric_ms(state.get("last_seen_ms"))
        if last_seen is None:
            # The telemetry Redis key itself has the DJI telemetry TTL, so an
            # extant legacy/state record without last_seen is still fresh.
            return True
        return now - last_seen <= ttl_ms

    # update_topo may arrive before the first OSD sample. Preserve a bounded
    # startup grace, but never let the persistent identity registry claim
    # "online" indefinitely after the telemetry TTL has elapsed.
    topology_seen = _numeric_ms(device.get("updated_at_ms"))
    return topology_seen is not None and now - topology_seen <= ttl_ms


def _updated_at_ms(
    device: Mapping[str, Any],
    state: Mapping[str, Any] | None,
) -> int | None:
    values = [
        value
        for value in (
            _numeric_ms(device.get("updated_at_ms")),
            _numeric_ms(state.get("last_seen_ms")) if state is not None else None,
            _numeric_ms(state.get("received_at_ms")) if state is not None else None,
        )
        if value is not None
    ]
    return max(values) if values else None


class DJICloudVehicleProvider:
    source = "dji_cloud"

    def __init__(self, redis: Redis):
        self.registry = DeviceRegistry(redis)
        self.telemetry = TelemetryStore(redis)

    async def list_vehicles(self) -> list[VehicleSnapshot]:
        result: list[VehicleSnapshot] = []
        for device in await self.registry.list_devices():
            if device.get("role") != "aircraft":
                continue
            sn = str(device["sn"])
            state = await self.telemetry.get(sn)
            result.append(
                VehicleSnapshot(
                    id=canonical_vehicle_id(sn),
                    sn=sn,
                    name=str(device.get("model") or sn),
                    model=str(device.get("model") or "UNKNOWN"),
                    source=self.source,
                    online=_device_online(device, state),
                    gateway_sn=device.get("gateway_sn"),
                    updated_at_ms=_updated_at_ms(device, state),
                    telemetry=normalize_aircraft_state(state, source=self.source),
                    sources=(self.source,),
                )
            )
        return result
