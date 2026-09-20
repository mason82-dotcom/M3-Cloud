from __future__ import annotations
import asyncio
import json
import math
import time
from typing import Any
import httpx
from app.config import settings
from app.vehicles.base import VehicleSnapshot, canonical_vehicle_id
from app.vehicles.payloads import AircraftPlatform, attach_payload_capabilities, platform_from_camera_type
from app.vehicles.state import normalize_aircraft_state

def _configured_hosts() -> list[str]:
    return [item.strip() for item in settings.lyrebird_hosts.split(",") if item.strip()]

def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None

def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def aircraft_serial(config: dict[str, Any]) -> str | None:
    value = config.get("aircraftSerialNumber")
    if not isinstance(value, str):
        return None
    serial = value.strip()
    if not serial or serial.upper() == "UNKNOWN":
        return None
    return serial


def merge_identity_config(
    config: dict[str, Any],
    settings_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """Backfill serial identity from /config/settings for older Lyrebird /config surfaces."""

    result = dict(config)
    if aircraft_serial(result) is None and isinstance(settings_snapshot, dict):
        serial = aircraft_serial(settings_snapshot)
        if serial is not None:
            result["aircraftSerialNumber"] = serial
    return result


def normalize_telemetry(raw: dict[str, Any], now_ms: int | None = None) -> dict[str, Any]:
    """Map Lyrebird TCP JSON to neutral M3-Cloud fields without inventing RTK/altitude data."""
    location = _object(raw.get("location"))
    attitude = _object(raw.get("attitude"))
    speed = _object(raw.get("speed"))
    phone = _object(raw.get("phoneLocation"))
    gimbal = _object(raw.get("gimbalAttitude"))
    north = _finite(speed.get("x") if "x" in speed else speed.get("north"))
    east = _finite(speed.get("y") if "y" in speed else speed.get("east"))
    horizontal_speed = math.hypot(north, east) if north is not None and east is not None else None
    return {
        "last_seen_ms": now_ms or int(time.time() * 1000),
        "source": "lyrebird_tcp",
        "latitude": _finite(location.get("latitude")),
        "longitude": _finite(location.get("longitude")),
        "relative_altitude_m": _finite(raw.get("altitude")),
        "horizontal_speed_mps": horizontal_speed,
        "vertical_speed_mps": _finite(speed.get("z") if "z" in speed else speed.get("up")),
        "heading_deg": _finite(raw.get("heading")),
        "gps_satellites": raw.get("satelliteCount") if isinstance(raw.get("satelliteCount"), int) else None,
        "battery": {
            "capacity_percent": raw.get("batteryLevel") if isinstance(raw.get("batteryLevel"), int) else None,
            "remain_flight_time_s": raw.get("remainingFlightTime") if isinstance(raw.get("remainingFlightTime"), int) else None,
        },
        "attitude": {"yaw_deg": _finite(attitude.get("yaw")), "roll_deg": _finite(attitude.get("roll")), "pitch_deg": _finite(attitude.get("pitch"))},
        "gimbal": {"yaw_deg": _finite(gimbal.get("yaw")), "roll_deg": _finite(gimbal.get("roll")), "pitch_deg": _finite(gimbal.get("pitch"))},
        "flight_mode": raw.get("flightMode"),
        "home_set": raw.get("homeSet"),
        "distance_to_home_m": _finite(raw.get("distanceToHome")),
        "camera": {"recording": raw.get("isRecording"), "zoom_ratio": _finite(raw.get("zoomRatio"))},
        "controller": {
            "latitude": _finite(phone.get("latitude")), "longitude": _finite(phone.get("longitude")),
            "heading_deg": _finite(phone.get("heading")),
            "battery_percent": phone.get("battery") if isinstance(phone.get("battery"), int) else None,
            "wifi_rssi_dbm": phone.get("wifiRssi") if isinstance(phone.get("wifiRssi"), int) else None,
        },
        "safety": {
            "ready_to_takeoff": raw.get("readyToTakeoff"),
            "takeoff_block_reason": raw.get("takeoffBlockReason"),
            "manual_override": raw.get("isManualOverrideActive"),
        },
    }

def merge_dicts(base: dict[str, Any] | None, update: dict[str, Any] | None, *, ignore_none: bool = False) -> dict[str, Any]:
    """Recursively merge telemetry without mutating either input."""
    merged: dict[str, Any] = {}
    for key, value in (base or {}).items():
        merged[key] = merge_dicts(value, None) if isinstance(value, dict) else value
    for key, value in (update or {}).items():
        if ignore_none and value is None:
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(merged[key], value, ignore_none=ignore_none)
        elif isinstance(value, dict):
            merged[key] = merge_dicts(None, value, ignore_none=ignore_none)
        else:
            merged[key] = value
    return merged

def merge_transport_telemetry(mavlink: dict[str, Any] | None, tcp: dict[str, Any] | None) -> dict[str, Any] | None:
    """Fuse transports recursively: TCP supplies gaps, MAVLink wins where both carry a fact."""
    if mavlink is None:
        return merge_dicts(None, tcp) if tcp is not None else None
    merged = merge_dicts(tcp, mavlink, ignore_none=True)
    merged["source"] = "lyrebird_mavlink2+tcp_gap" if tcp else "lyrebird_mavlink2"
    merged["provenance"] = {
        "primary": "mavlink2",
        "supplemental": ["tcp_gap"] if tcp else [],
        "policy": "recursive_mavlink_preferred",
    }
    return merged

def normalize_config(host: str, config: dict[str, Any], telemetry: dict[str, Any] | None = None, camera_capabilities: dict[str, Any] | None = None) -> VehicleSnapshot:
    name = str(config.get("droneName") or host)
    caps = camera_capabilities or {}
    # Lyrebird exposes both the raw DJI CameraType and its normalized platform.
    # Prefer CameraType, but accept the explicit normalized platform as a safe fallback.
    # Both values are product identity; capability flags such as hasThermal are deliberately
    # not used to infer M3E/M3T/M3M.
    platform = platform_from_camera_type(caps.get("cameraType"))
    if platform == AircraftPlatform.UNKNOWN:
        platform = platform_from_camera_type(caps.get("platform"))
    model = platform.value if platform != AircraftPlatform.UNKNOWN else "LYREBIRD_AIRCRAFT"
    enriched = attach_payload_capabilities(normalize_aircraft_state(telemetry, source="lyrebird"), platform)
    if enriched is not None and caps:
        enriched["payload"]["camera"] = {
            "component_index": caps.get("componentIndex"),
            "connected": caps.get("connected"),
            "camera_type": caps.get("cameraType"),
            "firmware_version": caps.get("firmwareVersion"),
            "camera_mode": caps.get("cameraMode"),
            "camera_mode_range": caps.get("cameraModeRange") or [],
            "live_view_source": caps.get("liveViewSource"),
            "live_view_source_range": caps.get("liveViewSourceRange") or [],
            "capture_stored_sources": caps.get("captureStoredSources") or [],
            "record_stored_sources": caps.get("recordStoredSources") or [],
            "capture_storage_read_status": caps.get("captureStorageReadStatus"),
            "record_storage_read_status": caps.get("recordStorageReadStatus"),
            "capture_current_screen": caps.get("captureCurrentScreen"),
        }

    serial = aircraft_serial(config)
    if serial is None:
        vehicle_id = f"lyrebird:{host}"
        vehicle_sn = f"lyrebird@{host}"
    else:
        vehicle_id = canonical_vehicle_id(serial)
        vehicle_sn = serial

    return VehicleSnapshot(
        id=vehicle_id,
        sn=vehicle_sn,
        name=name,
        model=model,
        source="lyrebird",
        online=True,
        updated_at_ms=int(time.time() * 1000),
        telemetry=enriched,
        sources=("lyrebird",),
    )

class LyrebirdVehicleProvider:
    source = "lyrebird"
    def __init__(self, client: httpx.AsyncClient | None = None, mavlink_collector: Any | None = None):
        self._client = client
        self._mavlink_collector = mavlink_collector

    async def _read_telemetry(self, host: str) -> dict[str, Any] | None:
        writer = None
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, settings.lyrebird_telemetry_port), timeout=settings.lyrebird_timeout_seconds)
            if self._mavlink_collector is not None:
                writer.write(b"MODE=GAP\n")
                await asyncio.wait_for(writer.drain(), timeout=settings.lyrebird_timeout_seconds)
            line = await asyncio.wait_for(reader.readline(), timeout=settings.lyrebird_timeout_seconds)
            raw = json.loads(line.decode("utf-8"))
            return normalize_telemetry(raw) if isinstance(raw, dict) else None
        except (OSError, asyncio.TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass

    async def _read_identity_settings(self, client: httpx.AsyncClient, host: str) -> dict[str, Any] | None:
        try:
            response = await client.get(
                f"http://{host}:{settings.lyrebird_http_port}/config/settings",
                timeout=settings.lyrebird_timeout_seconds,
                headers={"Connection": "close"},
            )
            response.raise_for_status()
            value = response.json()
            return value if isinstance(value, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    async def _read_camera_capabilities(self, client: httpx.AsyncClient, host: str) -> dict[str, Any] | None:
        try:
            response = await client.get(
                f"http://{host}:{settings.lyrebird_http_port}/get/camera/capabilities",
                timeout=settings.lyrebird_timeout_seconds,
                headers={"Connection": "close"},
            )
            response.raise_for_status()
            value = response.json()
            return value if isinstance(value, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    async def _probe(self, client: httpx.AsyncClient, host: str) -> VehicleSnapshot | None:
        try:
            response = await client.get(
                f"http://{host}:{settings.lyrebird_http_port}/config",
                timeout=settings.lyrebird_timeout_seconds,
                headers={"Connection": "close"},
            )
            response.raise_for_status()
            config = response.json()
            if not isinstance(config, dict):
                return None
            # Keep identity discovery strictly sequential on the RC. Field testing
            # shows that an active telemetry socket can interfere with the embedded
            # HTTP server even when the individual HTTP endpoint succeeds in isolation.
            camera_caps = await self._read_camera_capabilities(client, host)
            identity_settings = await self._read_identity_settings(client, host)
            tcp = await self._read_telemetry(host)
            config = merge_identity_config(config, identity_settings)
            mavlink = self._mavlink_collector.snapshot(host) if self._mavlink_collector is not None else None
            telemetry = merge_transport_telemetry(mavlink, tcp)
            return normalize_config(host, config, telemetry, camera_caps)
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
