from __future__ import annotations

from typing import Any

from pymavlink.dialects.v20 import common as mavlink_common

from app.dji.wpml import WPMLCompileError, compile_wpml_kmz


_PLATFORM_KEYS = {
    "M3E": ("0-77-0", ["1-66-0"]),
    "M3T": ("0-77-1", ["1-67-0"]),
    "M3M": ("0-77-2", ["1-68-0"]),
}


def mission_platform(plan: dict[str, object]) -> str:
    planning = plan.get("planning")
    value = (
        str(planning.get("platform") or "").strip().upper()
        if isinstance(planning, dict)
        else ""
    )
    aliases = {
        "DJI_MAVIC_3E": "M3E",
        "DJI_MAVIC_3T": "M3T",
        "DJI_MAVIC_3M": "M3M",
    }
    value = aliases.get(value, value)
    if value not in _PLATFORM_KEYS:
        raise WPMLCompileError("Mission does not declare M3E, M3T, or M3M platform")
    return value


def model_keys(platform: str) -> tuple[str, list[str]]:
    try:
        drone, payloads = _PLATFORM_KEYS[platform]
    except KeyError as exc:
        raise WPMLCompileError(f"Unsupported DJI wayline platform: {platform}") from exc
    return drone, list(payloads)


def start_wayline_point(plan: dict[str, object]) -> dict[str, float] | None:
    raw = plan.get("items")
    if not isinstance(raw, list):
        return None
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("command") != mavlink_common.MAV_CMD_NAV_WAYPOINT:
            continue
        lat = item.get("latitude_deg")
        lon = item.get("longitude_deg")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return {
                "start_latitude": float(lat),
                # DJI's public schema intentionally spells this "lontitude".
                "start_lontitude": float(lon),
            }
    return None


def compile_mission_wayline(
    plan: dict[str, object],
    *,
    name: str,
):
    platform = mission_platform(plan)
    return compile_wpml_kmz(
        plan,
        platform=platform,
        filename_stem=name,
    )


def wayline_list_item(
    *,
    mission_id: str,
    name: str,
    plan: dict[str, object],
    updated_at_ms: int,
) -> dict[str, Any]:
    platform = mission_platform(plan)
    # Validate that the mission is actually exportable before advertising it to Pilot 2.
    compile_mission_wayline(plan, name=name)
    drone_key, payload_keys = model_keys(platform)
    return {
        "id": mission_id,
        "drone_model_key": drone_key,
        "favorited": False,
        "name": name,
        "payload_model_keys": payload_keys,
        "template_types": [0],
        "action_type": 0,
        "update_time": updated_at_ms,
        "user_name": "M3-Cloud",
        "start_wayline_point": start_wayline_point(plan),
    }
