from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from pymavlink.dialects.v20 import common as mavlink_common


MAX_MISSION_ITEMS = 1000

LYREBIRD_UPLOAD_COMMANDS = frozenset(
    {
        mavlink_common.MAV_CMD_NAV_WAYPOINT,
        mavlink_common.MAV_CMD_NAV_TAKEOFF,
        mavlink_common.MAV_CMD_NAV_LAND,
        mavlink_common.MAV_CMD_NAV_RETURN_TO_LAUNCH,
        mavlink_common.MAV_CMD_DO_CHANGE_SPEED,
        mavlink_common.MAV_CMD_SET_CAMERA_MODE,
        mavlink_common.MAV_CMD_IMAGE_START_CAPTURE,
        mavlink_common.MAV_CMD_VIDEO_START_CAPTURE,
        mavlink_common.MAV_CMD_VIDEO_STOP_CAPTURE,
        mavlink_common.MAV_CMD_DO_GIMBAL_MANAGER_PITCHYAW,
        mavlink_common.MAV_CMD_DO_MOUNT_CONTROL,
        mavlink_common.MAV_CMD_DO_SET_CAM_TRIGG_DIST,
        mavlink_common.MAV_CMD_DO_SET_ROI_LOCATION,
        mavlink_common.MAV_CMD_DO_SET_ROI_NONE,
        mavlink_common.MAV_CMD_DO_SET_ROI,
    }
)


def normalize_plan(items: list[dict[str, Any]]) -> dict[str, object]:
    if len(items) > MAX_MISSION_ITEMS:
        raise ValueError(f"Mission exceeds {MAX_MISSION_ITEMS} items")

    normalized: list[dict[str, object]] = []
    for expected_seq, raw in enumerate(items):
        seq = raw.get("seq", expected_seq)
        if not isinstance(seq, int) or isinstance(seq, bool) or seq != expected_seq:
            raise ValueError("Mission item seq must be contiguous and start at zero")

        command = raw.get("command")
        if not isinstance(command, int) or isinstance(command, bool) or command < 0:
            raise ValueError(f"Mission item {seq} has invalid command")

        latitude = _finite(raw.get("latitude_deg", 0.0), f"item {seq} latitude")
        longitude = _finite(raw.get("longitude_deg", 0.0), f"item {seq} longitude")
        altitude = _finite(raw.get("altitude_m", 0.0), f"item {seq} altitude")
        if not -90.0 <= latitude <= 90.0:
            raise ValueError(f"Mission item {seq} latitude out of range")
        if not -180.0 <= longitude <= 180.0:
            raise ValueError(f"Mission item {seq} longitude out of range")

        params = [
            _nullable_finite(raw.get(f"param{index}"), f"item {seq} param{index}")
            for index in range(1, 5)
        ]

        normalized.append(
            {
                "seq": seq,
                "command": command,
                "param1": params[0],
                "param2": params[1],
                "param3": params[2],
                "param4": params[3],
                "latitude_deg": latitude,
                "longitude_deg": longitude,
                "altitude_m": altitude,
                "autocontinue": bool(raw.get("autocontinue", True)),
            }
        )

    payload: dict[str, object] = {
        "schema_version": 1,
        "protocol": "MAVLINK_MISSION",
        "items": normalized,
    }
    return payload


def plan_sha256(plan: dict[str, object]) -> str:
    encoded = json.dumps(
        plan,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compatibility(plan: dict[str, object]) -> dict[str, object]:
    raw_items = plan.get("items")
    items = raw_items if isinstance(raw_items, list) else []
    unsupported: list[dict[str, int]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        seq = item.get("seq")
        command = item.get("command")
        if isinstance(seq, int) and isinstance(command, int) and command not in LYREBIRD_UPLOAD_COMMANDS:
            unsupported.append({"seq": seq, "command": command})

    return {
        "m3cloud_execution_enabled": False,
        "lyrebird_mavlink_upload_compatible": not unsupported,
        "lyrebird_unsupported_items": unsupported,
        "dji_native_execution_compatible": None,
        "note": (
            "Planning/status only. M3-Cloud does not expose mission upload or execution "
            "actions in R6.1; DJI-native executability is therefore not asserted."
        ),
    }


def mission_state_name(value: Any) -> str:
    mapping = {
        1: "NO_MISSION",
        2: "NOT_STARTED",
        3: "ACTIVE",
        4: "PAUSED",
        5: "COMPLETE",
    }
    return mapping.get(value, "UNKNOWN") if isinstance(value, int) else "UNKNOWN"


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def _nullable_finite(value: Any, label: str) -> float | None:
    if value is None:
        return None
    return _finite(value, label)
