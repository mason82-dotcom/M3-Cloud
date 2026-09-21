from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.vehicles.base import VehicleProvider, VehicleSnapshot, canonical_vehicle_id


_SOURCE_PRIORITY = {
    "dji_cloud": 300,
    "lyrebird": 200,
}
_GENERIC_MODELS = {"", "UNKNOWN", "LYREBIRD_AIRCRAFT", "DJI"}
_UNKNOWN_FIXES = {None, "", "UNKNOWN", "NONE"}


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


def _preserve_auxiliary_positioning(
    merged: dict[str, Any] | None,
    *,
    primary: VehicleSnapshot,
    secondary: VehicleSnapshot,
) -> dict[str, Any] | None:
    """Keep source-native facts that DJI Cloud does not expose without dethroning it.

    Pilot-to-Cloud is the primary state source. Lyrebird may still provide an MSDK
    RTK FIX/FLOAT diagnostic that the M3 Pilot thing model does not expose. Preserve
    that fact only where the DJI Cloud value is explicitly unknown.
    """

    if (
        merged is None
        or primary.source != "dji_cloud"
        or secondary.source != "lyrebird"
        or not isinstance(primary.telemetry, dict)
        or not isinstance(secondary.telemetry, dict)
    ):
        return merged

    primary_state = primary.telemetry.get("aircraft_state")
    secondary_state = secondary.telemetry.get("aircraft_state")
    merged_state = merged.get("aircraft_state")
    if not all(
        isinstance(value, dict)
        for value in (primary_state, secondary_state, merged_state)
    ):
        return merged

    primary_positioning = primary_state.get("positioning")
    secondary_positioning = secondary_state.get("positioning")
    merged_positioning = merged_state.get("positioning")
    if not all(
        isinstance(value, dict)
        for value in (
            primary_positioning,
            secondary_positioning,
            merged_positioning,
        )
    ):
        return merged

    primary_fix = primary_positioning.get("fix")
    secondary_fix = secondary_positioning.get("fix")
    if primary_fix in _UNKNOWN_FIXES and secondary_fix not in _UNKNOWN_FIXES:
        merged_positioning["fix"] = deepcopy(secondary_fix)
        secondary_source = secondary_positioning.get("position_source")
        if secondary_source is not None:
            merged_positioning["position_source"] = deepcopy(secondary_source)
        if secondary_positioning.get("rtk_fixed") is not None:
            merged_positioning["rtk_fixed"] = deepcopy(
                secondary_positioning["rtk_fixed"]
            )

    primary_rtk = primary_positioning.get("rtk")
    secondary_rtk = secondary_positioning.get("rtk")
    if isinstance(secondary_rtk, dict):
        merged_positioning["rtk"] = _merge_dicts(
            primary_rtk if isinstance(primary_rtk, dict) else {},
            secondary_rtk,
        )

    merged_state["source"] = "dji_cloud"
    merged_state["positioning"] = merged_positioning
    merged["aircraft_state"] = merged_state
    return merged


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

    telemetry = _merge_dicts(secondary.telemetry, primary.telemetry)
    telemetry = _preserve_auxiliary_positioning(
        telemetry,
        primary=primary,
        secondary=secondary,
    )

    return VehicleSnapshot(
        id=canonical_vehicle_id(primary.sn),
        sn=primary.sn,
        name=primary.name or secondary.name,
        model=_model(primary, secondary),
        source=primary.source,
        online=left.online or right.online,
        gateway_sn=primary.gateway_sn or secondary.gateway_sn,
        updated_at_ms=max(timestamps) if timestamps else None,
        telemetry=telemetry,
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
