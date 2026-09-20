from __future__ import annotations

import asyncio
import math
import struct
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from pymavlink.dialects.v20 import common as mavlink_common
from pymavlink.generator.mavcrc import x25crc

from app.config import settings

AUTOPILOT_COMPONENT = 1
GCS_SYSTEM = 255
GCS_COMPONENT = 190
MAVLINK2_MAGIC = 0xFD
MAVLINK_ROUTE_STALE_TIMEOUT_S = 10.0

LYREBIRD_STATUS_ID = 42100
LYREBIRD_STATUS_STRUCT = "<IiiffIIIHHHhhHHHBBB24s"
LYREBIRD_STATUS_SIZE = 75
LYREBIRD_STATUS_CRC_EXTRA = 196
LYREBIRD_CONFIG_ID = 42101
LYREBIRD_CONFIG_STRUCT = "<HHB20s16s12s"
LYREBIRD_CONFIG_SIZE = 53
LYREBIRD_CONFIG_CRC_EXTRA = 201

LB_FLAG_MANUAL_OVERRIDE = 1
LB_FLAG_READY_TO_TAKEOFF = 2
LB_FLAG_HOME_SET = 4
LB_FLAG_LRF_TARGET_VALID = 8
LB_CONFIG_FLAG_HAS_THERMAL = 1

def _trim(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace").strip()

def _checksum_ok(frame: bytes, crc_extra: int) -> bool:
    if len(frame) < 12 or frame[0] != MAVLINK2_MAGIC:
        return False
    payload_length = frame[1]
    end = 10 + payload_length
    if len(frame) < end + 2:
        return False
    crc = x25crc(frame[1:end])
    crc.accumulate(bytes([crc_extra]))
    return crc.crc == (frame[end] | frame[end + 1] << 8)

def _mavlink2_frames(data: bytes):
    """Yield complete MAVLink-2 frames from a UDP datagram, including signed frames."""
    offset = 0
    while offset + 12 <= len(data):
        if data[offset] != MAVLINK2_MAGIC:
            offset += 1
            continue
        payload_length = data[offset + 1]
        signed = bool(data[offset + 2] & 0x01)
        size = 10 + payload_length + 2 + (13 if signed else 0)
        if offset + size > len(data):
            return
        yield data[offset:offset + size]
        offset += size

def decode_lyrebird_frame(frame: bytes) -> dict[str, Any]:
    if len(frame) < 12 or frame[0] != MAVLINK2_MAGIC:
        return {}
    message_id = int.from_bytes(frame[7:10], "little")
    payload = frame[10:10 + frame[1]]
    if message_id == LYREBIRD_CONFIG_ID:
        if not _checksum_ok(frame, LYREBIRD_CONFIG_CRC_EXTRA):
            return {}
        http_port, telemetry_port, flags, name, ip, video = struct.unpack(
            LYREBIRD_CONFIG_STRUCT, payload.ljust(LYREBIRD_CONFIG_SIZE, b"\x00")
        )
        return {"lyrebird": {"config": {
            "drone_name": _trim(name), "ip_address": _trim(ip),
            "http_port": http_port, "telemetry_port": telemetry_port,
            "video_mode": _trim(video), "has_thermal": bool(flags & LB_CONFIG_FLAG_HAS_THERMAL),
        }}}
    if message_id != LYREBIRD_STATUS_ID or not _checksum_ok(frame, LYREBIRD_STATUS_CRC_EXTRA):
        return {}
    values = struct.unpack(LYREBIRD_STATUS_STRUCT, payload.ljust(LYREBIRD_STATUS_SIZE, b"\x00"))
    (_boot, lrf_lat, lrf_lon, lrf_alt, max_radius, waypoint_seq, yaw_seq, altitude_seq,
     go_home_s, land_s, total_s, gimbal_pitch, gimbal_roll, zoom_fl, optical_fl, hybrid_fl,
     battery_home, battery_land, flags, reason) = values
    patch: dict[str, Any] = {
        "safety": {
            "manual_override": bool(flags & LB_FLAG_MANUAL_OVERRIDE),
            "ready_to_takeoff": bool(flags & LB_FLAG_READY_TO_TAKEOFF),
            "takeoff_block_reason": _trim(reason) or None,
        },
        "home_set": bool(flags & LB_FLAG_HOME_SET),
        "gimbal": {"joint_pitch_deg": gimbal_pitch / 100.0, "joint_roll_deg": gimbal_roll / 100.0},
        "camera": {
            "zoom_focal_length_mm": zoom_fl or None,
            "optical_focal_length_mm": optical_fl or None,
            "hybrid_focal_length_mm": hybrid_fl or None,
        },
        "flight_budget": {
            "max_radius_returnable_m": max_radius,
            "time_to_home_s": go_home_s, "time_to_land_s": land_s, "total_flight_time_s": total_s,
            "battery_to_home_percent": battery_home, "battery_to_land_percent": battery_land,
        },
        "reach": {"waypoint_seq": waypoint_seq, "yaw_seq": yaw_seq, "altitude_seq": altitude_seq},
    }
    if flags & LB_FLAG_LRF_TARGET_VALID:
        patch.setdefault("lrf", {})["target"] = {
            "latitude": lrf_lat / 1e7, "longitude": lrf_lon / 1e7, "altitude_m": lrf_alt
        }
    return patch

def _heading_deg(value: int) -> float | None:
    if value == 65535:
        return None
    return (value / 100.0) % 360.0

def normalize_mavlink_message(msg: Any) -> dict[str, Any]:
    """Map only facts carried by standard MAVLink messages; no altitude/RTK inference."""
    kind = msg.get_type()
    if kind == "GLOBAL_POSITION_INT":
        return {
            "latitude": msg.lat / 1e7,
            "longitude": msg.lon / 1e7,
            "amsl_altitude_m": msg.alt / 1000.0,
            "relative_altitude_m": msg.relative_alt / 1000.0,
            "velocity_north_mps": msg.vx / 100.0,
            "velocity_east_mps": msg.vy / 100.0,
            "vertical_speed_mps": msg.vz / 100.0,
            "heading_deg": _heading_deg(msg.hdg),
        }
    if kind == "GPS_RAW_INT":
        fix = int(msg.fix_type)
        return {
            "gps_satellites": None if int(msg.satellites_visible) == 255 else int(msg.satellites_visible),
            "gnss_fix_type": fix,
            "rtk": {
                "fix": "FIXED" if fix == 6 else "FLOAT" if fix == 5 else "NONE",
                "active": fix in (5, 6),
            },
        }
    if kind == "ATTITUDE":
        return {
            "attitude": {
                "roll_deg": math.degrees(msg.roll),
                "pitch_deg": math.degrees(msg.pitch),
                "yaw_deg": math.degrees(msg.yaw),
            }
        }
    if kind == "BATTERY_STATUS":
        return {
            "battery": {
                "capacity_percent": None if int(msg.battery_remaining) < 0 else int(msg.battery_remaining),
                "remain_flight_time_s": int(getattr(msg, "time_remaining", 0) or 0),
            }
        }
    if kind == "HOME_POSITION":
        return {
            "home": {
                "latitude": msg.latitude / 1e7,
                "longitude": msg.longitude / 1e7,
                "amsl_altitude_m": msg.altitude / 1000.0,
            }
        }
    if kind == "RC_CHANNELS":
        rssi = int(msg.rssi)
        return {"controller": {"airlink_rssi_raw": None if rssi == 255 else rssi}}
    if kind == "DISTANCE_SENSOR":
        return {"lrf": {"distance_m": msg.current_distance / 100.0}}
    if kind == "CAMERA_CAPTURE_STATUS":
        return {"camera": {"recording": int(msg.video_status) == 1}}
    if kind == "GIMBAL_DEVICE_ATTITUDE_STATUS":
        q = tuple(float(v) for v in msg.q)
        if len(q) == 4:
            w, x, y, z = q
            roll = math.atan2(2 * (w*x + y*z), 1 - 2 * (x*x + y*y))
            pitch = math.asin(max(-1.0, min(1.0, 2 * (w*y - z*x))))
            yaw = math.atan2(2 * (w*z + x*y), 1 - 2 * (y*y + z*z))
            gimbal = {"roll_deg": math.degrees(roll), "pitch_deg": math.degrees(pitch), "yaw_deg": math.degrees(yaw)}
            delta_yaw = getattr(msg, "delta_yaw", None)
            if delta_yaw is not None and math.isfinite(float(delta_yaw)):
                gimbal["joint_yaw_deg"] = math.degrees(float(delta_yaw))
            return {"gimbal": gimbal}
    return {}

def _deep_merge(base: dict[str, Any], update: dict[str, Any]) -> None:
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value

class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, owner: "LyrebirdMavlinkCollector"):
        self.owner = owner
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.owner.feed_datagram(data, addr[0])

class LyrebirdMavlinkCollector:
    """Shared MAVLink-2 UDP collector keyed by configured Lyrebird host address."""
    def __init__(self) -> None:
        self._publisher: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None
        self._publish_tasks: set[asyncio.Task[None]] = set()
        self._transport: asyncio.DatagramTransport | None = None
        self._parsers: dict[str, Any] = {}
        self._state: dict[str, dict[str, Any]] = defaultdict(dict)
        self._seen: dict[str, float] = {}
        self._system_by_host: dict[str, int] = {}
        self._host_by_system: dict[int, str] = {}
        self._duplicate_system: dict[str, int] = {}
        self._heartbeat_task: asyncio.Task[None] | None = None

    def set_publisher(self, publisher: Callable[[str, dict[str, Any]], Awaitable[None]] | None) -> None:
        self._publisher = publisher

    def _schedule_publish(self, host: str) -> None:
        if self._publisher is None:
            return
        snapshot = self.snapshot(host)
        if snapshot is None:
            return
        task = asyncio.create_task(self._publisher(host, snapshot))
        self._publish_tasks.add(task)
        task.add_done_callback(self._publish_tasks.discard)

    async def start(self) -> None:
        if not settings.lyrebird_enabled or self._transport is not None:
            return
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _Protocol(self), local_addr=("0.0.0.0", settings.lyrebird_mavlink_port)
        )
        self._transport = transport
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        if self._publish_tasks:
            await asyncio.gather(*tuple(self._publish_tasks), return_exceptions=True)
            self._publish_tasks.clear()

    @staticmethod
    def _identity(msg: Any) -> tuple[int | None, int | None]:
        header = msg.get_header()
        return getattr(header, "srcSystem", None), getattr(header, "srcComponent", None)

    def _bind_system(self, host: str, system_id: int) -> bool:
        if not 1 <= system_id <= 254:
            return False
        existing_host = self._host_by_system.get(system_id)
        if existing_host is not None and existing_host != host:
            seen = self._seen.get(existing_host, 0.0)
            if seen and time.monotonic() - seen <= MAVLINK_ROUTE_STALE_TIMEOUT_S:
                self._duplicate_system[host] = system_id
                return False
            self._system_by_host.pop(existing_host, None)
            self._host_by_system.pop(system_id, None)
        previous = self._system_by_host.get(host)
        if previous is not None and previous != system_id and self._host_by_system.get(previous) == host:
            self._host_by_system.pop(previous, None)
        self._system_by_host[host] = system_id
        self._host_by_system[system_id] = host
        self._duplicate_system.pop(host, None)
        return True

    def route_status(self, host: str) -> dict[str, Any]:
        return {"system_id": self._system_by_host.get(host), "duplicate_system_id": self._duplicate_system.get(host)}

    def feed_datagram(self, data: bytes, host: str) -> None:
        allowed = {item.strip() for item in settings.lyrebird_hosts.split(",") if item.strip()}
        if host not in allowed:
            return
        parser = self._parsers.get(host)
        if parser is None:
            parser = mavlink_common.MAVLink(None); parser.robust_parsing = True; self._parsers[host] = parser
        messages = parser.parse_buffer(data) or []
        heartbeat_system_id = None
        for msg in messages:
            system_id, component_id = self._identity(msg)
            if msg.get_type() == "HEARTBEAT" and component_id == AUTOPILOT_COMPONENT and system_id is not None:
                heartbeat_system_id = int(system_id); break
        bound = self._system_by_host.get(host)
        if heartbeat_system_id is not None and heartbeat_system_id != bound:
            if not self._bind_system(host, heartbeat_system_id): return
            bound = heartbeat_system_id
        if bound is None or self._host_by_system.get(bound) != host: return
        changed = False
        for frame in _mavlink2_frames(data):
            if frame[5] != bound: continue
            patch = decode_lyrebird_frame(frame)
            if patch: _deep_merge(self._state[host], patch); changed = True
        for msg in messages:
            system_id, _ = self._identity(msg)
            if system_id != bound: continue
            patch = normalize_mavlink_message(msg)
            if patch: _deep_merge(self._state[host], patch); changed = True
        if changed or heartbeat_system_id is not None: self._seen[host] = time.monotonic()
        if changed: self._schedule_publish(host)

    def snapshot(self, host: str) -> dict[str, Any] | None:
        seen = self._seen.get(host)
        if seen is None or time.monotonic() - seen > settings.lyrebird_mavlink_ttl_seconds:
            return None
        result = dict(self._state.get(host, {}))
        result["source"] = "lyrebird_mavlink2"
        result["mavlink_route"] = self.route_status(host)
        result["last_seen_ms"] = int(time.time() * 1000)
        return result

    async def _heartbeat_loop(self) -> None:
        sink = bytearray()
        class Sink:
            def write(self, data: bytes) -> None:
                sink.extend(data)
        mav = mavlink_common.MAVLink(Sink(), srcSystem=GCS_SYSTEM, srcComponent=GCS_COMPONENT)
        mav.heartbeat_send(mavlink_common.MAV_TYPE_GCS, mavlink_common.MAV_AUTOPILOT_INVALID, 0, 0, mavlink_common.MAV_STATE_ACTIVE)
        frame = bytes(sink)
        while True:
            if self._transport is not None:
                for host in [x.strip() for x in settings.lyrebird_hosts.split(",") if x.strip()]:
                    self._transport.sendto(frame, (host, settings.lyrebird_mavlink_peer_port))
            await asyncio.sleep(1.0)

lyrebird_mavlink_collector = LyrebirdMavlinkCollector()
