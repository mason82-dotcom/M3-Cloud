from __future__ import annotations

import json
import time
from copy import deepcopy
from typing import Any, Mapping, Protocol

from redis.asyncio import Redis

from app.config import settings
from app.dji.protocol import PropertyMessage
from app.dji.topics import TopicKind


class TelemetryObserver(Protocol):
    async def ingest(self, telemetry: dict[str, Any]) -> None:
        ...


POSITION_CONVERGENCE = {
    0: "NOT_STARTED",
    1: "CONVERGING",
    2: "CONVERGED",
    3: "FAILED",
}


def deep_merge(base: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge dict properties; arrays and scalars are replaced as whole values."""

    merged = deepcopy(dict(base))
    for key, value in patch.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) else None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _camera(camera: Any) -> dict[str, Any] | None:
    if not isinstance(camera, dict):
        return None

    keys = (
        "payload_index",
        "camera_mode",
        "photo_state",
        "recording_state",
        "record_time",
        "remain_photo_num",
        "remain_record_duration",
        "screen_split_enable",
        "zoom_factor",
        "ir_zoom_factor",
        "photo_storage_settings",
        "video_storage_settings",
        "ir_metering_mode",
        "ir_metering_point",
        "ir_metering_area",
        "thermal_gain_mode",
    )
    return {key: deepcopy(camera[key]) for key in keys if key in camera}


def _battery(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    result: dict[str, Any] = {}
    mapping = {
        "capacity_percent": "capacity_percent",
        "remain_flight_time": "remain_flight_time_s",
        "return_home_power": "return_home_power_percent",
        "landing_power": "landing_power_percent",
    }
    for source, target in mapping.items():
        if source in value:
            result[target] = deepcopy(value[source])

    batteries = value.get("batteries")
    if isinstance(batteries, list):
        details = []
        allowed = (
            "index",
            "sn",
            "type",
            "sub_type",
            "firmware_version",
            "capacity_percent",
            "loop_times",
            "voltage",
            "temperature",
            "high_voltage_storage_days",
        )
        for battery in batteries:
            if isinstance(battery, dict):
                details.append({key: deepcopy(battery[key]) for key in allowed if key in battery})
        result["batteries"] = details

    return result


def normalize_telemetry(
    raw: Mapping[str, Any],
    *,
    source_sn: str,
    gateway_sn: str | None,
    source_timestamp_ms: int,
    received_at_ms: int | None = None,
) -> dict[str, Any]:
    """Normalize M3 aircraft properties without changing DJI altitude/RTK semantics."""

    received = received_at_ms if received_at_ms is not None else int(time.time() * 1000)

    state: dict[str, Any] = {
        "source_sn": source_sn,
        "gateway_sn": gateway_sn,
        "source_timestamp_ms": source_timestamp_ms,
        "received_at_ms": received,
        "last_seen_ms": received,
    }

    scalar_mapping = {
        "latitude": "latitude",
        "longitude": "longitude",
        "elevation": "relative_altitude_m",
        "height": "ellipsoid_height_m",
        "horizontal_speed": "horizontal_speed_mps",
        "vertical_speed": "vertical_speed_mps",
        "mode_code": "mode_code",
        "mode_code_reason": "mode_code_reason",
        "track_id": "track_id",
        "home_distance": "home_distance_m",
        "home_latitude": "home_latitude",
        "home_longitude": "home_longitude",
        "wind_speed": "wind_speed_mps",
        "wind_direction": "wind_direction_code",
        "control_source": "control_source",
        "gear": "gear_code",
    }
    for source, target in scalar_mapping.items():
        if source in raw:
            state[target] = deepcopy(raw[source])

    attitude = {}
    for source, target in (
        ("attitude_head", "yaw_deg"),
        ("attitude_roll", "roll_deg"),
        ("attitude_pitch", "pitch_deg"),
    ):
        value = _number(raw.get(source))
        if value is not None:
            attitude[target] = value
    if attitude:
        state["attitude"] = attitude

    position = raw.get("position_state")
    if isinstance(position, dict):
        code = _integer(position.get("is_fixed"))
        state["position_state"] = {
            "code": code,
            "convergence": POSITION_CONVERGENCE.get(code, "UNKNOWN"),
            "quality": _integer(position.get("quality")),
            "gps_satellites": _integer(position.get("gps_number")),
            "rtk_satellites": _integer(position.get("rtk_number")),
        }

    battery = _battery(raw.get("battery"))
    if battery is not None:
        state["battery"] = battery

    cameras = raw.get("cameras")
    if isinstance(cameras, list):
        normalized_cameras = [item for camera in cameras if (item := _camera(camera)) is not None]
        state["cameras"] = normalized_cameras

    # RC Pro / Pilot 2 gateway state is transported through the same OSD/state
    # topics but has a different thing model. Preserve the documented gateway
    # capabilities required by the primary DJI Cloud API control plane.
    for key in (
        "live_capacity",
        "live_status",
        "is_cloud_control_auth",
        "cloud_control_auth_state",
    ):
        if key in raw:
            state[key] = deepcopy(raw[key])

    return state


class TelemetryStore:
    """Merge DJI OSD/state property streams and cache normalized current aircraft state."""

    def __init__(
        self,
        redis: Redis,
        observer: TelemetryObserver | None = None,
    ):
        self.redis = redis
        self.observer = observer

    @staticmethod
    def key(sn: str) -> str:
        return f"dji:telemetry:{sn}"

    @staticmethod
    def raw_key(sn: str, kind: TopicKind) -> str:
        return f"dji:telemetry:{sn}:raw:{kind.value}"

    async def update(
        self,
        *,
        source_sn: str,
        kind: TopicKind,
        message: PropertyMessage,
    ) -> dict[str, Any]:
        if kind not in (TopicKind.OSD, TopicKind.STATE):
            raise ValueError(f"unsupported telemetry topic kind: {kind}")

        raw_record = {
            "timestamp": message.timestamp,
            "gateway": message.gateway,
            "from": message.from_sn,
            "data": message.data,
        }

        raw_ttl = (
            settings.dji_state_cache_ttl_seconds
            if kind is TopicKind.STATE
            else settings.dji_telemetry_ttl_seconds
        )
        await self.redis.set(
            self.raw_key(source_sn, kind),
            json.dumps(raw_record),
            ex=raw_ttl,
        )

        osd_raw, state_raw = await self.redis.mget(
            self.raw_key(source_sn, TopicKind.OSD),
            self.raw_key(source_sn, TopicKind.STATE),
        )

        merged: dict[str, Any] = {}
        latest_timestamp = message.timestamp
        gateway_sn = message.gateway

        for encoded in (osd_raw, state_raw):
            if not encoded:
                continue
            record = json.loads(encoded)
            data = record.get("data")
            if isinstance(data, dict):
                merged = deep_merge(merged, data)
            timestamp = record.get("timestamp")
            if isinstance(timestamp, int):
                latest_timestamp = max(latest_timestamp, timestamp)
            record_gateway = record.get("gateway")
            if isinstance(record_gateway, str) and record_gateway:
                gateway_sn = record_gateway

        normalized = normalize_telemetry(
            merged,
            source_sn=source_sn,
            gateway_sn=gateway_sn,
            source_timestamp_ms=latest_timestamp,
        )
        await self.redis.set(
            self.key(source_sn),
            json.dumps(normalized),
            ex=settings.dji_telemetry_ttl_seconds,
        )

        await self.redis.publish(
            settings.live_redis_channel,
            json.dumps(
                {
                    "type": "telemetry",
                    "device_sn": source_sn,
                    "timestamp": normalized["received_at_ms"],
                    "state": normalized,
                }
            ),
        )
        if kind is TopicKind.OSD and self.observer is not None:
            sample_state = dict(normalized)
            sample_state["source_timestamp_ms"] = message.timestamp
            await self.observer.ingest(sample_state)

        return normalized

    async def get(self, sn: str) -> dict[str, Any] | None:
        raw = await self.redis.get(self.key(sn))
        return json.loads(raw) if raw else None
