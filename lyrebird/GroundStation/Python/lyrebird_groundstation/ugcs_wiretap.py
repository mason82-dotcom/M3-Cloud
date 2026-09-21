"""Fail-closed MAVLink 2 wiretap for UgCS PX4 VSM <-> Lyrebird bench validation.

The proxy records the protocol exactly as it crosses the wire, while safe dry-run mode forwards
only an explicit non-flight allowlist. Unknown messages, MAVLink 1 bytes, malformed/incomplete
frames, parameter writes and direct actuator/flight commands are blocked as a whole datagram.

This is a bench-validation guard, not an authentication boundary. MAVLink signing remains the
aircraft-side trust mechanism.
"""

from __future__ import annotations  # noqa: I001

import argparse
import contextlib
import hashlib
import json
import math
import os
import socket
import struct
import threading
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lyrebird_groundstation.dji_client import DJIInterface


MAVLINK2_MAGIC = 0xFD
MAVLINK2_HEADER_BYTES = 10
MAVLINK2_SIGNATURE_BYTES = 13

MSG_HEARTBEAT = 0
MSG_PING = 4
MSG_SET_MODE = 11
MSG_PARAM_REQUEST_READ = 20
MSG_PARAM_REQUEST_LIST = 21
MSG_PARAM_SET = 23
MSG_MISSION_REQUEST_PARTIAL_LIST = 37
MSG_MISSION_WRITE_PARTIAL_LIST = 38
MSG_MISSION_ITEM = 39
MSG_MISSION_REQUEST = 40
MSG_MISSION_SET_CURRENT = 41
MSG_MISSION_CURRENT = 42
MSG_MISSION_REQUEST_LIST = 43
MSG_MISSION_COUNT = 44
MSG_MISSION_CLEAR_ALL = 45
MSG_MISSION_ITEM_REACHED = 46
MSG_MISSION_ACK = 47
MSG_MISSION_REQUEST_INT = 51
MSG_REQUEST_DATA_STREAM = 66
MSG_MANUAL_CONTROL = 69
MSG_RC_CHANNELS_OVERRIDE = 70
MSG_MISSION_ITEM_INT = 73
MSG_COMMAND_INT = 75
MSG_COMMAND_LONG = 76
MSG_COMMAND_ACK = 77
MSG_FILE_TRANSFER_PROTOCOL = 110
MSG_TIMESYNC = 111
MSG_PARAM_EXT_REQUEST_READ = 320
MSG_PARAM_EXT_REQUEST_LIST = 321
MSG_PARAM_EXT_SET = 323

COMMAND_NAMES = {
    16: "NAV_WAYPOINT",
    20: "NAV_RETURN_TO_LAUNCH",
    21: "NAV_LAND",
    22: "NAV_TAKEOFF",
    115: "CONDITION_YAW",
    176: "DO_SET_MODE",
    178: "DO_CHANGE_SPEED",
    179: "DO_SET_HOME",
    192: "DO_REPOSITION",
    195: "DO_SET_ROI_LOCATION",
    197: "DO_SET_ROI_NONE",
    201: "DO_SET_ROI",
    205: "DO_MOUNT_CONTROL",
    206: "DO_SET_CAM_TRIGG_DIST",
    224: "DO_SET_MISSION_CURRENT",
    245: "PREFLIGHT_STORAGE",
    262: "DO_SET_STANDARD_MODE",
    300: "MISSION_START",
    400: "COMPONENT_ARM_DISARM",
    410: "GET_HOME_POSITION",
    511: "SET_MESSAGE_INTERVAL",
    512: "REQUEST_MESSAGE",
    519: "REQUEST_PROTOCOL_VERSION",
    520: "REQUEST_AUTOPILOT_CAPABILITIES",
    521: "REQUEST_CAMERA_INFORMATION",
    522: "REQUEST_CAMERA_SETTINGS",
    525: "REQUEST_STORAGE_INFORMATION",
    527: "REQUEST_CAMERA_CAPTURE_STATUS",
    530: "SET_CAMERA_MODE",
    531: "SET_CAMERA_ZOOM",
    1000: "DO_GIMBAL_MANAGER_PITCHYAW",
    2000: "IMAGE_START_CAPTURE",
    2500: "VIDEO_START_CAPTURE",
    2501: "VIDEO_STOP_CAPTURE",
    2504: "REQUEST_VIDEO_STREAM_INFORMATION",
    2505: "REQUEST_VIDEO_STREAM_STATUS",
}

MESSAGE_NAMES = {
    MSG_HEARTBEAT: "HEARTBEAT",
    MSG_PING: "PING",
    MSG_SET_MODE: "SET_MODE",
    MSG_PARAM_REQUEST_READ: "PARAM_REQUEST_READ",
    MSG_PARAM_REQUEST_LIST: "PARAM_REQUEST_LIST",
    MSG_PARAM_SET: "PARAM_SET",
    MSG_MISSION_REQUEST_PARTIAL_LIST: "MISSION_REQUEST_PARTIAL_LIST",
    MSG_MISSION_WRITE_PARTIAL_LIST: "MISSION_WRITE_PARTIAL_LIST",
    MSG_MISSION_ITEM: "MISSION_ITEM",
    MSG_MISSION_REQUEST: "MISSION_REQUEST",
    MSG_MISSION_SET_CURRENT: "MISSION_SET_CURRENT",
    MSG_MISSION_CURRENT: "MISSION_CURRENT",
    MSG_MISSION_REQUEST_LIST: "MISSION_REQUEST_LIST",
    MSG_MISSION_COUNT: "MISSION_COUNT",
    MSG_MISSION_CLEAR_ALL: "MISSION_CLEAR_ALL",
    MSG_MISSION_ITEM_REACHED: "MISSION_ITEM_REACHED",
    MSG_MISSION_ACK: "MISSION_ACK",
    MSG_MISSION_REQUEST_INT: "MISSION_REQUEST_INT",
    MSG_REQUEST_DATA_STREAM: "REQUEST_DATA_STREAM",
    MSG_MANUAL_CONTROL: "MANUAL_CONTROL",
    MSG_RC_CHANNELS_OVERRIDE: "RC_CHANNELS_OVERRIDE",
    MSG_MISSION_ITEM_INT: "MISSION_ITEM_INT",
    MSG_COMMAND_INT: "COMMAND_INT",
    MSG_COMMAND_LONG: "COMMAND_LONG",
    MSG_COMMAND_ACK: "COMMAND_ACK",
    MSG_FILE_TRANSFER_PROTOCOL: "FILE_TRANSFER_PROTOCOL",
    MSG_TIMESYNC: "TIMESYNC",
    MSG_PARAM_EXT_REQUEST_READ: "PARAM_EXT_REQUEST_READ",
    MSG_PARAM_EXT_REQUEST_LIST: "PARAM_EXT_REQUEST_LIST",
    MSG_PARAM_EXT_SET: "PARAM_EXT_SET",
}

# Safe dry-run is intentionally not "everything except known movement". Only messages whose
# semantics are acceptable on the bench are forwarded. This is the fail-closed distinction from
# the original Phase-9 prototype.
SAFE_GCS_MESSAGE_IDS = {
    MSG_HEARTBEAT,
    MSG_PING,
    MSG_PARAM_REQUEST_READ,
    MSG_PARAM_REQUEST_LIST,
    MSG_MISSION_REQUEST_PARTIAL_LIST,
    MSG_MISSION_REQUEST,
    MSG_MISSION_REQUEST_LIST,
    MSG_MISSION_COUNT,
    MSG_MISSION_ACK,
    MSG_MISSION_REQUEST_INT,
    MSG_REQUEST_DATA_STREAM,
    MSG_MISSION_ITEM_INT,
    MSG_COMMAND_ACK,
    MSG_TIMESYNC,
    MSG_PARAM_EXT_REQUEST_READ,
    MSG_PARAM_EXT_REQUEST_LIST,
}

# Commands that may change telemetry/reporting state or request data, but cannot arm, move the
# vehicle, actuate the payload or change mission execution. Every other COMMAND_LONG/COMMAND_INT is
# blocked in dry-run mode.
SAFE_DRY_RUN_COMMANDS = {
    410,  # MAV_CMD_GET_HOME_POSITION
    511,  # MAV_CMD_SET_MESSAGE_INTERVAL
    512,  # MAV_CMD_REQUEST_MESSAGE
    519,  # MAV_CMD_REQUEST_PROTOCOL_VERSION
    520,  # MAV_CMD_REQUEST_AUTOPILOT_CAPABILITIES
    521,  # MAV_CMD_REQUEST_CAMERA_INFORMATION
    522,  # MAV_CMD_REQUEST_CAMERA_SETTINGS
    525,  # MAV_CMD_REQUEST_STORAGE_INFORMATION
    527,  # MAV_CMD_REQUEST_CAMERA_CAPTURE_STATUS
    2504,  # MAV_CMD_REQUEST_VIDEO_STREAM_INFORMATION
    2505,  # MAV_CMD_REQUEST_VIDEO_STREAM_STATUS
}

DRY_RUN_BLOCKED_MESSAGE_REASONS = {
    MSG_MISSION_CLEAR_ALL: "MISSION_CLEAR_ALL",
    MSG_PARAM_SET: "PARAM_SET",
    MSG_PARAM_EXT_SET: "PARAM_EXT_SET",
    MSG_SET_MODE: "SET_MODE",
    MSG_MANUAL_CONTROL: "MANUAL_CONTROL",
    MSG_RC_CHANNELS_OVERRIDE: "RC_CHANNELS_OVERRIDE",
    MSG_MISSION_SET_CURRENT: "MISSION_SET_CURRENT",
    MSG_MISSION_WRITE_PARTIAL_LIST: "MISSION_WRITE_PARTIAL_LIST",
    MSG_MISSION_ITEM: "MISSION_ITEM (non-INT upload not accepted in dry-run)",
    MSG_FILE_TRANSFER_PROTOCOL: "FILE_TRANSFER_PROTOCOL not allowlisted in dry-run",
}


@dataclass(frozen=True)
class MavlinkFrame:
    message_id: int
    sequence: int
    system_id: int
    component_id: int
    payload: bytes
    signed: bool
    raw: bytes


def split_mavlink2_frames(datagram: bytes) -> tuple[list[MavlinkFrame], bytes]:
    """Split complete MAVLink 2 frames and return every undecoded byte separately.

    The wiretap does not rewrite frames and does not need the dialect CRC table; checksum and
    signature verification remain the receiver's job. Structural ambiguity is nevertheless unsafe
    in dry-run mode, so any returned noise causes the whole datagram to be blocked there.
    """
    frames: list[MavlinkFrame] = []
    noise = bytearray()
    offset = 0

    while offset < len(datagram):
        if datagram[offset] != MAVLINK2_MAGIC:
            noise.append(datagram[offset])
            offset += 1
            continue

        if offset + MAVLINK2_HEADER_BYTES + 2 > len(datagram):
            noise.extend(datagram[offset:])
            break

        payload_len = datagram[offset + 1]
        incompat_flags = datagram[offset + 2]
        signed = bool(incompat_flags & 0x01)
        frame_len = (
            MAVLINK2_HEADER_BYTES + payload_len + 2 + (MAVLINK2_SIGNATURE_BYTES if signed else 0)
        )
        if offset + frame_len > len(datagram):
            noise.extend(datagram[offset:])
            break

        raw = datagram[offset : offset + frame_len]
        frames.append(
            MavlinkFrame(
                message_id=int.from_bytes(raw[7:10], "little"),
                sequence=raw[4],
                system_id=raw[5],
                component_id=raw[6],
                payload=raw[10 : 10 + payload_len],
                signed=signed,
                raw=raw,
            )
        )
        offset += frame_len

    return frames, bytes(noise)


def _padded(payload: bytes, length: int = 255) -> bytes:
    return payload if len(payload) >= length else payload + b"\x00" * (length - len(payload))


def _json_float(value: float) -> float | str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Inf" if value > 0 else "-Inf"
    return value


def _decode_mission_count(frame: MavlinkFrame, payload: bytes) -> dict[str, Any]:
    return {
        "count": struct.unpack_from("<H", payload, 0)[0],
        "targetSystem": payload[2],
        "targetComponent": payload[3],
        "missionType": payload[4] if len(frame.payload) > 4 else 0,
    }


def _decode_mission_request(frame: MavlinkFrame, payload: bytes) -> dict[str, Any]:
    return {
        "missionSeq": struct.unpack_from("<H", payload, 0)[0],
        "targetSystem": payload[2],
        "targetComponent": payload[3],
        "missionType": payload[4] if len(frame.payload) > 4 else 0,
    }


def _decode_mission_item_int(frame: MavlinkFrame, payload: bytes) -> dict[str, Any]:
    p1, p2, p3, p4 = struct.unpack_from("<ffff", payload, 0)
    x, y = struct.unpack_from("<ii", payload, 16)
    z = struct.unpack_from("<f", payload, 24)[0]
    mission_seq, command = struct.unpack_from("<HH", payload, 28)
    return {
        "missionSeq": mission_seq,
        "command": command,
        "commandName": COMMAND_NAMES.get(command, f"MAV_CMD_{command}"),
        "targetSystem": payload[32],
        "targetComponent": payload[33],
        "frame": payload[34],
        "current": payload[35],
        "autocontinue": payload[36],
        "missionType": payload[37] if len(frame.payload) > 37 else 0,
        "param1": _json_float(p1),
        "param2": _json_float(p2),
        "param3": _json_float(p3),
        "param4": _json_float(p4),
        "latitudeE7": x,
        "longitudeE7": y,
        "latitude": x / 1e7,
        "longitude": y / 1e7,
        "altitude": _json_float(z),
    }


def _decode_command(frame: MavlinkFrame, payload: bytes) -> dict[str, Any]:
    command = struct.unpack_from("<H", payload, 28)[0]
    data: dict[str, Any] = {
        "command": command,
        "commandName": COMMAND_NAMES.get(command, f"MAV_CMD_{command}"),
        "targetSystem": payload[30],
        "targetComponent": payload[31],
    }
    if frame.message_id == MSG_COMMAND_LONG:
        params = struct.unpack_from("<fffffff", payload, 0)
        data["params"] = [_json_float(value) for value in params]
        return data

    p1, p2, p3, p4 = struct.unpack_from("<ffff", payload, 0)
    x, y = struct.unpack_from("<ii", payload, 16)
    z = struct.unpack_from("<f", payload, 24)[0]
    data["params"] = [
        _json_float(p1),
        _json_float(p2),
        _json_float(p3),
        _json_float(p4),
        x / 1e7,
        y / 1e7,
        _json_float(z),
    ]
    data["frame"] = payload[32]
    return data


def _decode_mission_ack(frame: MavlinkFrame, payload: bytes) -> dict[str, Any]:
    return {
        "targetSystem": payload[0],
        "targetComponent": payload[1],
        "result": payload[2],
        "missionType": payload[3] if len(frame.payload) > 3 else 0,
    }


def _decode_command_ack(payload: bytes) -> dict[str, Any]:
    return {
        "command": struct.unpack_from("<H", payload, 0)[0],
        "result": payload[2],
    }


def _decode_set_mode(payload: bytes) -> dict[str, Any]:
    return {
        "customMode": struct.unpack_from("<I", payload, 0)[0],
        "targetSystem": payload[4],
        "baseMode": payload[5],
    }


def _decode_frame_payload(frame: MavlinkFrame, payload: bytes) -> dict[str, Any]:
    if frame.message_id == MSG_MISSION_COUNT:
        return _decode_mission_count(frame, payload)
    if frame.message_id in {MSG_MISSION_REQUEST, MSG_MISSION_REQUEST_INT}:
        return _decode_mission_request(frame, payload)
    if frame.message_id == MSG_MISSION_ITEM_INT:
        return _decode_mission_item_int(frame, payload)
    if frame.message_id in {MSG_COMMAND_LONG, MSG_COMMAND_INT}:
        return _decode_command(frame, payload)
    if frame.message_id == MSG_MISSION_ACK:
        return _decode_mission_ack(frame, payload)
    if frame.message_id == MSG_COMMAND_ACK:
        return _decode_command_ack(payload)
    if frame.message_id == MSG_SET_MODE:
        return _decode_set_mode(payload)
    return {}


def decode_frame(frame: MavlinkFrame) -> dict[str, Any]:
    """Decode only fields needed for safety policy and mission forensics."""
    data: dict[str, Any] = {
        "messageId": frame.message_id,
        "message": MESSAGE_NAMES.get(frame.message_id, f"MSG_{frame.message_id}"),
        "sequence": frame.sequence,
        "systemId": frame.system_id,
        "componentId": frame.component_id,
        "signed": frame.signed,
    }
    data.update(_decode_frame_payload(frame, _padded(frame.payload)))
    return data


def should_block_dry_run(frame: MavlinkFrame) -> tuple[bool, str | None]:
    """Fail-closed frame policy for VSM -> RC traffic."""
    decoded = decode_frame(frame)

    if frame.message_id == MSG_MISSION_COUNT:
        if decoded.get("count", 0) == 0:
            return True, "MISSION_COUNT(count=0) would clear the stored mission"
        return False, None

    if frame.message_id in SAFE_GCS_MESSAGE_IDS:
        return False, None

    if frame.message_id in {MSG_COMMAND_LONG, MSG_COMMAND_INT}:
        command = int(decoded.get("command", -1))
        if command in SAFE_DRY_RUN_COMMANDS:
            return False, None
        name = COMMAND_NAMES.get(command, f"MAV_CMD_{command}")
        return True, f"{decoded['message']}:{name}"

    explicit_reason = DRY_RUN_BLOCKED_MESSAGE_REASONS.get(frame.message_id)
    if explicit_reason is not None:
        return True, explicit_reason
    return True, f"unallowlisted {decoded['message']}"


def should_block_dry_run_datagram(datagram: bytes) -> tuple[bool, str | None]:
    """Block the whole UDP datagram if any byte/frame cannot be proven safe."""
    frames, noise = split_mavlink2_frames(datagram)
    if not frames:
        return True, "no complete MAVLink 2 frame"
    if noise:
        return True, f"{len(noise)} undecoded/non-MAVLink byte(s)"

    reasons: list[str] = []
    for frame in frames:
        blocked, reason = should_block_dry_run(frame)
        if blocked:
            reasons.append(reason or f"message {frame.message_id}")

    if reasons:
        return True, "; ".join(dict.fromkeys(reasons))
    return False, None


class JsonlRecorder:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")
        self._lock = threading.Lock()
        self._datagram_id = 0
        self._closed = False

    def record(
        self,
        direction: str,
        source: tuple[str, int],
        destination: tuple[str, int],
        datagram: bytes,
        *,
        blocked: bool = False,
        block_reason: str | None = None,
    ) -> None:
        frames, noise = split_mavlink2_frames(datagram)
        now = datetime.now(timezone.utc).isoformat()
        epoch_ns = time.time_ns()

        with self._lock:
            if self._closed:
                return
            self._datagram_id += 1
            base: dict[str, Any] = {
                "timestamp": now,
                "epochNs": epoch_ns,
                "datagramId": self._datagram_id,
                "direction": direction,
                "source": f"{source[0]}:{source[1]}",
                "destination": f"{destination[0]}:{destination[1]}",
                "bytes": len(datagram),
                "blocked": blocked,
            }
            if block_reason:
                base["blockReason"] = block_reason

            if frames:
                for frame in frames:
                    row = {**base, **decode_frame(frame), "rawHex": frame.raw.hex()}
                    self._handle.write(json.dumps(row, separators=(",", ":")) + "\n")
            else:
                self._handle.write(
                    json.dumps(
                        {**base, "message": "UNDECODED_DATAGRAM", "rawHex": datagram.hex()},
                        separators=(",", ":"),
                    )
                    + "\n"
                )
            if noise:
                self._handle.write(
                    json.dumps(
                        {**base, "message": "NON_MAVLINK_BYTES", "rawHex": noise.hex()},
                        separators=(",", ":"),
                    )
                    + "\n"
                )
            self._handle.flush()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._handle.close()


class UgcsWiretapProxy:
    def __init__(
        self,
        *,
        rc_host: str,
        listen_host: str = "127.0.0.1",
        listen_port: int = 14560,
        aircraft_port: int = 14550,
        aircraft_local_port: int = 0,
        output_path: str | Path,
        safe_dry_run: bool = True,
    ):
        rc_ip = socket.gethostbyname(rc_host)
        self.rc = (rc_ip, aircraft_port)
        self.listen = (listen_host, listen_port)
        self.aircraft_local_port = aircraft_local_port
        self.safe_dry_run = safe_dry_run
        self.recorder = JsonlRecorder(output_path)

        self._vsm_socket: socket.socket | None = None
        self._aircraft_socket: socket.socket | None = None
        self._vsm_peer: tuple[str, int] | None = None
        self._running = threading.Event()
        self._peer_lock = threading.Lock()

    def _accept_vsm_peer(self, peer: tuple[str, int], *, structurally_valid: bool) -> bool:
        """Pin the first structurally valid VSM peer; never silently rebind during a run."""
        with self._peer_lock:
            if self._vsm_peer is None:
                if not structurally_valid:
                    return False
                self._vsm_peer = peer
                return True
            return peer == self._vsm_peer

    def start(self) -> None:
        vsm = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        vsm.bind(self.listen)
        vsm.settimeout(0.5)

        aircraft = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        aircraft.bind(("0.0.0.0", self.aircraft_local_port))
        # Connected UDP pins the RC endpoint in the kernel: unrelated datagrams are not delivered
        # to recvfrom(), and send() cannot accidentally target a different aircraft.
        aircraft.connect(self.rc)
        aircraft.settimeout(0.5)

        self._vsm_socket = vsm
        self._aircraft_socket = aircraft
        self._running.set()

        threads = [
            threading.Thread(target=self._pump_vsm_to_aircraft, name="wiretap-vsm", daemon=True),
            threading.Thread(target=self._pump_aircraft_to_vsm, name="wiretap-rc", daemon=True),
        ]
        for thread in threads:
            thread.start()

        print(
            f"UgCS wiretap listening on {self.listen[0]}:{self.listen[1]} -> "
            f"{self.rc[0]}:{self.rc[1]}"
        )
        print(f"Aircraft-side local UDP port: {aircraft.getsockname()[1]}")
        print(f"Safe dry-run: {'ON (fail-closed)' if self.safe_dry_run else 'OFF / LIVE FLIGHT'}")
        try:
            while self._running.is_set():
                time.sleep(0.25)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
            for thread in threads:
                thread.join(timeout=1.0)

    def stop(self) -> None:
        self._running.clear()
        for sock in (self._vsm_socket, self._aircraft_socket):
            if sock is not None:
                with contextlib.suppress(OSError):
                    sock.close()
        self.recorder.close()

    def _vsm_peer_rejection_reason(self) -> str:
        if self._vsm_peer is None:
            return "invalid first datagram; peer not pinned"
        return f"VSM peer mismatch; pinned={self._vsm_peer[0]}:{self._vsm_peer[1]}"

    def _record_rejected_vsm_peer(self, peer: tuple[str, int], data: bytes) -> None:
        self.recorder.record(
            "VSM_TO_RC",
            peer,
            self.rc,
            data,
            blocked=True,
            block_reason=self._vsm_peer_rejection_reason(),
        )

    def _vsm_forwarding_decision(self, data: bytes) -> tuple[bool, str | None]:
        if self.safe_dry_run:
            return should_block_dry_run_datagram(data)
        return False, None

    def _send_vsm_datagram_to_aircraft(self, data: bytes) -> bool:
        assert self._aircraft_socket is not None
        try:
            self._aircraft_socket.send(data)
        except OSError:
            return False
        return True

    def _pump_vsm_to_aircraft(self) -> None:
        assert self._vsm_socket is not None
        assert self._aircraft_socket is not None

        while self._running.is_set():
            try:
                data, peer = self._vsm_socket.recvfrom(65535)
            except TimeoutError:
                continue
            except OSError:
                return

            frames, noise = split_mavlink2_frames(data)
            structurally_valid = bool(frames) and not noise
            if not self._accept_vsm_peer(peer, structurally_valid=structurally_valid):
                self._record_rejected_vsm_peer(peer, data)
                continue

            blocked, reason = self._vsm_forwarding_decision(data)
            self.recorder.record(
                "VSM_TO_RC",
                peer,
                self.rc,
                data,
                blocked=blocked,
                block_reason=reason,
            )
            if not blocked and not self._send_vsm_datagram_to_aircraft(data):
                return

    def _pump_aircraft_to_vsm(self) -> None:
        assert self._vsm_socket is not None
        assert self._aircraft_socket is not None

        while self._running.is_set():
            try:
                data, peer = self._aircraft_socket.recvfrom(65535)
            except TimeoutError:
                continue
            except OSError:
                return

            with self._peer_lock:
                vsm_peer = self._vsm_peer
            if vsm_peer is None:
                continue

            self.recorder.record("RC_TO_VSM", peer, vsm_peer, data)
            try:
                self._vsm_socket.sendto(data, vsm_peer)
            except OSError:
                return


def _new_wiretap_capture(row: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "expectedCount": None if row is None else int(row["count"]),
        "missionCountEpochNs": None if row is None else row.get("epochNs"),
        "itemsBySeq": {},
        "acceptedAck": False,
        "ackEpochNs": None,
    }


def _starts_mission_upload(row: dict[str, Any]) -> bool:
    return (
        row.get("direction") == "VSM_TO_RC"
        and row.get("message") == "MISSION_COUNT"
        and not row.get("blocked")
        and int(row.get("count", 0)) > 0
    )


def _is_mission_item_row(row: dict[str, Any], capture: dict[str, Any]) -> bool:
    return (
        row.get("direction") == "VSM_TO_RC"
        and row.get("message") == "MISSION_ITEM_INT"
        and not row.get("blocked")
        and capture["expectedCount"] is not None
    )


def _is_mission_ack_row(row: dict[str, Any], capture: dict[str, Any]) -> bool:
    return (
        row.get("direction") == "RC_TO_VSM"
        and row.get("message") == "MISSION_ACK"
        and capture["expectedCount"] is not None
    )


def _apply_wiretap_row(
    capture: dict[str, Any],
    row: dict[str, Any],
) -> dict[str, Any]:
    if _starts_mission_upload(row):
        return _new_wiretap_capture(row)
    if _is_mission_item_row(row, capture):
        capture["itemsBySeq"][int(row["missionSeq"])] = row
        return capture
    if _is_mission_ack_row(row, capture):
        capture["acceptedAck"] = int(row.get("result", -1)) == 0
        capture["ackEpochNs"] = row.get("epochNs")
    return capture


def load_wiretap_capture(path: str | Path) -> dict[str, Any]:
    """Return the latest VSM mission-upload transaction represented in a JSONL capture."""
    capture = _new_wiretap_capture()
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            capture = _apply_wiretap_row(capture, json.loads(line))

    items_by_seq = capture.pop("itemsBySeq")
    capture["items"] = [items_by_seq[index] for index in sorted(items_by_seq)]
    return capture


def load_wiretap_mission(path: str | Path) -> list[dict[str, Any]]:
    """Compatibility helper returning only the latest upload's MISSION_ITEM_INT rows."""
    return list(load_wiretap_capture(path)["items"])


def _as_float(value: Any) -> float:
    if isinstance(value, str):
        lowered = value.lower()
        if lowered == "nan":
            return float("nan")
        if lowered == "inf":
            return float("inf")
        if lowered == "-inf":
            return float("-inf")
    return float(value)


def _canonical_float(value: Any) -> bytes:
    number = _as_float(value)
    if math.isnan(number):
        return struct.pack("<I", 0x7FC00000)
    return struct.pack("<f", number)


def _java_round(value: float) -> int:
    return math.floor(value + 0.5)


def canonical_mission_item(item: dict[str, Any]) -> bytes:
    """Android MavlinkMission.kt's 35-byte logical MISSION_ITEM_INT representation."""
    data = bytearray()
    for name in ("param1", "param2", "param3", "param4"):
        data.extend(_canonical_float(item.get(name, 0.0)))

    latitude_e7 = item.get("latitudeE7")
    if latitude_e7 is None:
        latitude_e7 = _java_round(float(item.get("latitude", 0.0)) * 1e7)
    longitude_e7 = item.get("longitudeE7")
    if longitude_e7 is None:
        longitude_e7 = _java_round(float(item.get("longitude", 0.0)) * 1e7)

    data.extend(struct.pack("<i", int(latitude_e7)))
    data.extend(struct.pack("<i", int(longitude_e7)))
    data.extend(_canonical_float(item.get("altitude", 0.0)))
    data.extend(
        struct.pack(
            "<HHBBB",
            int(item.get("missionSeq", item.get("seq", 0))) & 0xFFFF,
            int(item.get("command", 0)) & 0xFFFF,
            int(item.get("frame", 0)) & 0xFF,
            1 if bool(item.get("autocontinue", False)) else 0,
            int(item.get("missionType", 0)) & 0xFF,
        )
    )
    return bytes(data)


def mission_digest(items: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in items:
        digest.update(canonical_mission_item(item))
    return digest.hexdigest()


def mission_plan_id(items: list[dict[str, Any]]) -> int:
    crc = 0
    for item in items:
        crc = zlib.crc32(canonical_mission_item(item), crc)
    return crc & 0xFFFFFFFF


def _numbers_equal(left: Any, right: Any, tolerance: float) -> bool:
    if left == right:
        return True
    if str(left).lower() == "nan" and str(right).lower() == "nan":
        return True
    try:
        return math.isclose(float(left), float(right), rel_tol=1e-6, abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def _compare_capture_metadata(
    wire_items: list[dict[str, Any]],
    wire_metadata: dict[str, Any] | None,
) -> list[str]:
    if wire_metadata is None:
        return []

    differences: list[str] = []
    expected = wire_metadata.get("expectedCount")
    if expected is not None and int(expected) != len(wire_items):
        differences.append(
            f"wire upload incomplete: expected={int(expected)} captured={len(wire_items)}"
        )
    if expected is not None and not wire_metadata.get("acceptedAck"):
        differences.append("no accepted RC MISSION_ACK observed for latest upload")
    return differences


def _compare_item(
    wire: dict[str, Any],
    rc: dict[str, Any],
    *,
    index: int,
    float_tolerance: float,
) -> list[str]:
    prefix = f"seq {wire.get('missionSeq', index)}"
    differences: list[str] = []

    for wire_key, rc_key in (
        ("missionSeq", "seq"),
        ("command", "command"),
        ("frame", "frame"),
        ("autocontinue", "autocontinue"),
    ):
        left = wire.get(wire_key)
        right = rc.get(rc_key)
        if wire_key == "autocontinue":
            left = bool(left)
            right = bool(right)
        if left != right:
            differences.append(f"{prefix}: {wire_key} wire={left!r} rc={right!r}")

    for wire_key, rc_key in (
        ("param1", "param1"),
        ("param2", "param2"),
        ("param3", "param3"),
        ("param4", "param4"),
        ("latitude", "latitude"),
        ("longitude", "longitude"),
        ("altitude", "altitude"),
    ):
        left = wire.get(wire_key)
        right = rc.get(rc_key)
        if not _numbers_equal(left, right, float_tolerance):
            differences.append(f"{prefix}: {wire_key} wire={left!r} rc={right!r}")

    return differences


def _mission_digest_comparison(
    wire_items: list[dict[str, Any]],
    rc_trace: dict[str, Any],
) -> tuple[str, str, str | None]:
    wire_digest = mission_digest(wire_items) if wire_items else ""
    rc_digest = str(rc_trace.get("missionDigest") or "")
    if wire_items and rc_digest and wire_digest != rc_digest:
        return wire_digest, rc_digest, (
            f"mission digest differs: wire={wire_digest} rc={rc_digest}"
        )
    return wire_digest, rc_digest, None


def _mission_plan_id_comparison(
    wire_items: list[dict[str, Any]],
    rc_trace: dict[str, Any],
) -> tuple[int, int | None, str | None]:
    wire_plan_id = mission_plan_id(wire_items) if wire_items else 0
    rc_plan_id_raw = rc_trace.get("planId")
    rc_plan_id = int(rc_plan_id_raw) & 0xFFFFFFFF if rc_plan_id_raw is not None else None
    if wire_items and rc_plan_id is not None and wire_plan_id != rc_plan_id:
        return wire_plan_id, rc_plan_id, (
            f"mission planId differs: wire={wire_plan_id:#010x} rc={rc_plan_id:#010x}"
        )
    return wire_plan_id, rc_plan_id, None


def _compare_mission_identity(
    wire_items: list[dict[str, Any]],
    rc_trace: dict[str, Any],
) -> tuple[list[str], str, str, int, int | None]:
    wire_digest, rc_digest, digest_difference = _mission_digest_comparison(
        wire_items,
        rc_trace,
    )
    wire_plan_id, rc_plan_id, plan_difference = _mission_plan_id_comparison(
        wire_items,
        rc_trace,
    )
    differences = [
        difference
        for difference in (digest_difference, plan_difference)
        if difference is not None
    ]
    return differences, wire_digest, rc_digest, wire_plan_id, rc_plan_id


def _capture_clock_diagnostics(
    wire_items: list[dict[str, Any]],
    rc_trace: dict[str, Any],
) -> tuple[int | None, int | None, int | None]:
    epochs = [int(row["epochNs"]) for row in wire_items if row.get("epochNs") is not None]
    wire_last_epoch_ms = max(epochs) // 1_000_000 if epochs else None
    rc_uploaded_epoch_ms = int(rc_trace.get("uploadedAtEpochMs") or 0) or None
    if wire_last_epoch_ms is None or rc_uploaded_epoch_ms is None:
        return wire_last_epoch_ms, rc_uploaded_epoch_ms, None

    # Diagnostic only: these timestamps come from two devices and their wall clocks may differ.
    return (
        wire_last_epoch_ms,
        rc_uploaded_epoch_ms,
        rc_uploaded_epoch_ms - wire_last_epoch_ms,
    )


def compare_wiretap_to_rc(
    wire_items: list[dict[str, Any]],
    rc_trace: dict[str, Any],
    *,
    float_tolerance: float = 1e-5,
    wire_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare the bytes UgCS uploaded with Lyrebird's canonical accepted mission trace."""
    rc_items = sorted(rc_trace.get("items") or [], key=lambda row: int(row.get("seq", 0)))
    wire_items = sorted(wire_items, key=lambda row: int(row.get("missionSeq", row.get("seq", 0))))
    differences = _compare_capture_metadata(wire_items, wire_metadata)

    if len(wire_items) != len(rc_items):
        differences.append(f"item count differs: wire={len(wire_items)} rc={len(rc_items)}")

    for index, (wire, rc) in enumerate(zip(wire_items, rc_items, strict=False)):
        differences.extend(
            _compare_item(
                wire,
                rc,
                index=index,
                float_tolerance=float_tolerance,
            )
        )

    identity = _compare_mission_identity(wire_items, rc_trace)
    identity_differences, wire_digest, rc_digest, wire_plan_id, rc_plan_id = identity
    differences.extend(identity_differences)

    wire_last_epoch_ms, rc_uploaded_epoch_ms, clock_delta_ms = _capture_clock_diagnostics(
        wire_items,
        rc_trace,
    )

    return {
        "ok": not differences,
        "wireItems": len(wire_items),
        "rcItems": len(rc_items),
        "wireMissionDigest": wire_digest,
        "rcMissionDigest": rc_digest or None,
        "wirePlanId": wire_plan_id,
        "rcPlanId": rc_plan_id,
        "acceptedAck": None if wire_metadata is None else bool(wire_metadata.get("acceptedAck")),
        "wireLastItemEpochMs": wire_last_epoch_ms,
        "rcUploadedAtEpochMs": rc_uploaded_epoch_ms,
        "clockDeltaMs": clock_delta_ms,
        "differences": differences,
    }


def _default_output() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("ugcs-wiretap") / f"ugcs-wiretap-{stamp}.jsonl"


def _compare(path: Path, rc_host: str) -> int:
    client = DJIInterface(rc_host, query_config_name=True)
    trace = client.getLatestMissionTrace()
    if trace is None:
        print("No Lyrebird mission trace available for comparison.")
        return 2

    capture = load_wiretap_capture(path)
    result = compare_wiretap_to_rc(
        list(capture["items"]),
        trace,
        wire_metadata=capture,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 2


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fail-closed UgCS PX4-VSM <-> Lyrebird MAVLink 2 UDP wiretap."
    )
    parser.add_argument("--rc", default=os.getenv("LYREBIRD_RC"))
    parser.add_argument("--listen-address", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=14560)
    parser.add_argument("--aircraft-port", type=int, default=14550)
    parser.add_argument("--aircraft-local-port", type=int, default=0)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--live-flight",
        action="store_true",
        help=(
            "Disable the dry-run filter and forward pinned-peer datagrams unchanged. "
            "Use only after wire/mission validation."
        ),
    )
    parser.add_argument(
        "--compare",
        type=Path,
        metavar="WIRETAP_JSONL",
        help="Do not proxy; compare a capture with the RC's currently accepted mission trace.",
    )
    args = parser.parse_args()

    if not args.rc:
        parser.error("--rc or LYREBIRD_RC is required")

    if args.compare is not None:
        raise SystemExit(_compare(args.compare, args.rc))

    output = args.output or _default_output()
    proxy = UgcsWiretapProxy(
        rc_host=args.rc,
        listen_host=args.listen_address,
        listen_port=args.listen_port,
        aircraft_port=args.aircraft_port,
        aircraft_local_port=args.aircraft_local_port,
        output_path=output,
        safe_dry_run=not args.live_flight,
    )
    print(f"Capture: {output}")
    proxy.start()


if __name__ == "__main__":
    main()
