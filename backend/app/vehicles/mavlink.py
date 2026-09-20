from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict
from typing import Any

from pymavlink.dialects.v20 import common as mavlink_common

from app.config import settings

AUTOPILOT_COMPONENT = 1
GCS_SYSTEM = 255
GCS_COMPONENT = 190

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
        self._transport: asyncio.DatagramTransport | None = None
        self._parsers: dict[str, Any] = {}
        self._state: dict[str, dict[str, Any]] = defaultdict(dict)
        self._seen: dict[str, float] = {}
        self._heartbeat_task: asyncio.Task[None] | None = None

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

    def feed_datagram(self, data: bytes, host: str) -> None:
        allowed = {item.strip() for item in settings.lyrebird_hosts.split(",") if item.strip()}
        if host not in allowed:
            return
        parser = self._parsers.get(host)
        if parser is None:
            parser = mavlink_common.MAVLink(None)
            parser.robust_parsing = True
            self._parsers[host] = parser
        for msg in parser.parse_buffer(data) or []:
            header = msg.get_header()
            if getattr(header, "srcComponent", None) == AUTOPILOT_COMPONENT or msg.get_type() in {
                "BATTERY_STATUS", "RC_CHANNELS", "HOME_POSITION"
            }:
                patch = normalize_mavlink_message(msg)
                if patch:
                    _deep_merge(self._state[host], patch)
                    self._seen[host] = time.monotonic()

    def snapshot(self, host: str) -> dict[str, Any] | None:
        seen = self._seen.get(host)
        if seen is None or time.monotonic() - seen > settings.lyrebird_mavlink_ttl_seconds:
            return None
        result = dict(self._state.get(host, {}))
        result["source"] = "lyrebird_mavlink2"
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
