from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib
from typing import Any

from pymavlink.dialects.v20 import common as mavlink_common


MAX_MISSION_ITEMS = 1000
MAV_FRAME_GLOBAL_RELATIVE_ALT = 3
MAV_FRAME_GLOBAL_RELATIVE_ALT_INT = 6
LYREBIRD_RELATIVE_GLOBAL_FRAMES = frozenset(
    {MAV_FRAME_GLOBAL_RELATIVE_ALT, MAV_FRAME_GLOBAL_RELATIVE_ALT_INT}
)

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


def normalize_plan(
    items: list[dict[str, Any]],
    *,
    planning: dict[str, Any] | None = None,
) -> dict[str, object]:
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

        frame = raw.get("frame", MAV_FRAME_GLOBAL_RELATIVE_ALT_INT)
        if (
            not isinstance(frame, int)
            or isinstance(frame, bool)
            or not 0 <= frame <= 255
        ):
            raise ValueError(f"Mission item {seq} has invalid frame")

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
                "frame": frame,
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
        "schema_version": 2,
        "protocol": "MAVLINK_MISSION",
        "items": normalized,
    }
    if planning is not None:
        try:
            encoded = json.dumps(planning, allow_nan=False, separators=(",", ":"))
            copied = json.loads(encoded)
        except (TypeError, ValueError) as exc:
            raise ValueError("Mission planning context must be finite JSON data") from exc
        if not isinstance(copied, dict):
            raise ValueError("Mission planning context must be an object")
        payload["planning"] = copied
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
    unsupported_frames: list[dict[str, int | None]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        seq = item.get("seq")
        command = item.get("command")
        if isinstance(seq, int) and isinstance(command, int) and command not in LYREBIRD_UPLOAD_COMMANDS:
            unsupported.append({"seq": seq, "command": command})

        frame = item.get("frame")
        if not isinstance(frame, int) or isinstance(frame, bool):
            unsupported_frames.append(
                {"seq": seq if isinstance(seq, int) else -1, "frame": None}
            )
        elif frame not in LYREBIRD_RELATIVE_GLOBAL_FRAMES:
            unsupported_frames.append(
                {"seq": seq if isinstance(seq, int) else -1, "frame": frame}
            )

    wire_ready = bool(items) and not unsupported and not unsupported_frames
    return {
        "m3cloud_execution_enabled": False,
        "wire_ready": wire_ready,
        "lyrebird_mavlink_upload_compatible": wire_ready,
        "lyrebird_unsupported_items": unsupported,
        "lyrebird_unsupported_frames": unsupported_frames,
        "dji_native_execution_compatible": None,
        "note": (
            "Planning/handoff only. New M3-Cloud revisions persist MAV_FRAME explicitly. "
            "M3-Cloud may upload a sealed package when the server upload gate is enabled; "
            "mission execution actions remain disabled."
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



def compile_mission_item_int(plan: dict[str, object]) -> dict[str, object]:
    """Compile a normalized plan to logical MISSION_ITEM_INT fields without sending it."""

    info = compatibility(plan)
    if not info["wire_ready"]:
        raise ValueError("Mission plan is not wire-ready")

    raw_items = plan.get("items")
    items = raw_items if isinstance(raw_items, list) else []
    compiled: list[dict[str, object]] = []

    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("Mission plan contains a non-object item")

        latitude = float(raw["latitude_deg"])
        longitude = float(raw["longitude_deg"])
        # Kotlin/Lyrebird roundToInt rounds half values toward +infinity.
        x = math.floor(latitude * 10_000_000 + 0.5)
        y = math.floor(longitude * 10_000_000 + 0.5)
        if not -(2**31) <= x < 2**31 or not -(2**31) <= y < 2**31:
            raise ValueError("Mission coordinate does not fit MISSION_ITEM_INT")

        compiled.append(
            {
                "seq": int(raw["seq"]),
                "frame": int(raw["frame"]),
                "command": int(raw["command"]),
                "current": 0,
                "autocontinue": 1 if bool(raw.get("autocontinue", True)) else 0,
                "param1": raw.get("param1"),
                "param2": raw.get("param2"),
                "param3": raw.get("param3"),
                "param4": raw.get("param4"),
                "x": x,
                "y": y,
                "z": float(raw["altitude_m"]),
                "mission_type": 0,
            }
        )

    return {
        "message": "MISSION_ITEM_INT",
        "target_system": "RUNTIME",
        "target_component": "RUNTIME",
        "null_float_encoding": "IEEE754_NAN",
        "items": compiled,
    }



def mission_runtime_id(wire: dict[str, object]) -> int:
    """Compute the same uint32 mission_id Lyrebird reports in MISSION_CURRENT."""

    raw_items = wire.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return 0

    crc = 0

    def f32(value: object) -> bytes:
        if value is None:
            bits = 0x7FC00000
        else:
            number = float(value)
            if math.isnan(number):
                bits = 0x7FC00000
            else:
                return struct.pack("<f", number)
        return struct.pack("<I", bits)

    for item in raw_items:
        if not isinstance(item, dict):
            raise ValueError("Wire mission contains non-object item")
        chunk = bytearray()
        for key in ("param1", "param2", "param3", "param4"):
            chunk.extend(f32(item.get(key)))
        chunk.extend(struct.pack("<i", int(item["x"])))
        chunk.extend(struct.pack("<i", int(item["y"])))
        chunk.extend(f32(item["z"]))
        chunk.extend(struct.pack("<H", int(item["seq"]) & 0xFFFF))
        chunk.extend(struct.pack("<H", int(item["command"]) & 0xFFFF))
        chunk.extend(struct.pack("<B", int(item["frame"]) & 0xFF))
        chunk.extend(struct.pack("<B", int(item["autocontinue"]) & 0xFF))
        chunk.extend(struct.pack("<B", int(item.get("mission_type", 0)) & 0xFF))
        crc = zlib.crc32(chunk, crc)

    return crc & 0xFFFFFFFF
