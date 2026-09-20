from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.vehicles.base import VehicleProvider, VehicleSnapshot, canonical_vehicle_id


_SOURCE_PRIORITY = {
    "lyrebird": 200,
    "dji_cloud": 100,
}
_GENERIC_MODELS = {"", "UNKNOWN", "LYREBIRD_AIRCRAFT", "DJI"}


def _priority(vehicle: VehicleSnapshot) -> tuple[int, int]:
    return (
        _SOURCE_PRIORITY.get(vehicle.source, 0),
        vehicle.updated_at_ms or 0,
    )


def _sources(vehicle: VehicleSnapshot) -> tuple[str, ...]:
    return vehicle.sources or (vehicle.source,)


def _merge_dicts(
    base: dict[str, Any] | None,
    overlay: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Overlay higher-priority telemetry without letting null erase a valid fallback fact."""

    if base is None and overlay is None:
        return None

    merged: dict[str, Any] = deepcopy(base or {})
    for key, value in (overlay or {}).items():
        if value is None:
            continue
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(current, value) or {}
        else:
            merged[key] = deepcopy(value)
    return merged


def _model(primary: VehicleSnapshot, secondary: VehicleSnapshot) -> str:
    if primary.model not in _GENERIC_MODELS:
        return primary.model
    if secondary.model not in _GENERIC_MODELS:
        return secondary.model
    return primary.model or secondary.model


def merge_vehicle_snapshots(
    left: VehicleSnapshot,
    right: VehicleSnapshot,
) -> VehicleSnapshot:
    if left.sn != right.sn:
        raise ValueError("cannot merge different aircraft serials")

    primary, secondary = (
        (left, right) if _priority(left) >= _priority(right) else (right, left)
    )
    sources = tuple(dict.fromkeys((*_sources(primary), *_sources(secondary))))
    timestamps = [
        value
        for value in (left.updated_at_ms, right.updated_at_ms)
        if value is not None
    ]

    return VehicleSnapshot(
        id=canonical_vehicle_id(primary.sn),
        sn=primary.sn,
        name=primary.name or secondary.name,
        model=_model(primary, secondary),
        source=primary.source,
        online=left.online or right.online,
        gateway_sn=primary.gateway_sn or secondary.gateway_sn,
        updated_at_ms=max(timestamps) if timestamps else None,
        telemetry=_merge_dicts(secondary.telemetry, primary.telemetry),
        sources=sources,
    )


class VehicleRegistry:
    def __init__(self, providers: list[VehicleProvider]):
        self.providers = providers

    async def list_vehicles(self) -> list[VehicleSnapshot]:
        merged: dict[str, VehicleSnapshot] = {}
        for provider in self.providers:
            for vehicle in await provider.list_vehicles():
                current = merged.get(vehicle.sn)
                merged[vehicle.sn] = (
                    vehicle
                    if current is None
                    else merge_vehicle_snapshots(current, vehicle)
                )
        return sorted(merged.values(), key=lambda item: (item.model, item.sn))
