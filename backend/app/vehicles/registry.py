from __future__ import annotations

from app.vehicles.base import VehicleProvider, VehicleSnapshot


class VehicleRegistry:
    def __init__(self, providers: list[VehicleProvider]):
        self.providers = providers

    async def list_vehicles(self) -> list[VehicleSnapshot]:
        merged: dict[str, VehicleSnapshot] = {}
        for provider in self.providers:
            for vehicle in await provider.list_vehicles():
                # Prefer the freshest record if two transports describe one SN.
                current = merged.get(vehicle.sn)
                current_ts = current.updated_at_ms or 0 if current else -1
                next_ts = vehicle.updated_at_ms or 0
                if current is None or next_ts >= current_ts:
                    merged[vehicle.sn] = vehicle
        return sorted(merged.values(), key=lambda item: (item.model, item.sn))
