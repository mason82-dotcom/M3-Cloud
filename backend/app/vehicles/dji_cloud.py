from __future__ import annotations

from redis.asyncio import Redis

from app.dji.registry import DeviceRegistry
from app.dji.telemetry import TelemetryStore
from app.vehicles.base import VehicleSnapshot
from app.vehicles.state import normalize_aircraft_state


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
                    id=f"dji:{sn}",
                    sn=sn,
                    name=str(device.get("model") or sn),
                    model=str(device.get("model") or "UNKNOWN"),
                    source=self.source,
                    online=bool(device.get("online", False)),
                    gateway_sn=device.get("gateway_sn"),
                    updated_at_ms=device.get("updated_at_ms"),
                    telemetry=normalize_aircraft_state(state, source=self.source),
                )
            )
        return result
