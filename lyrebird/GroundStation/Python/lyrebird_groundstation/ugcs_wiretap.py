"""Fail-closed MAVLink 2 wiretap for UgCS PX4 VSM <-> Lyrebird.

The proxy records the exact datagrams on both sides. In the default dry-run mode it forwards only
an explicit allowlist needed to discover the vehicle and upload/read a mission. Any undecodable
bytes, MAVLink 1 frame, state-changing parameter write, unknown command or unknown MAVLink 2
message blocks the complete VSM->RC datagram.

Use --live-flight only after the captured mission matches Lyrebird's accepted mission trace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import socket
import struct
import threading
import time
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
MSG_PARAM_REQUEST_READ = 20
MSG_PARAM_REQUEST_LIST = 21
MSG_PARAM_SET = 23
MSG_MISSION_REQUEST_LIST = 43
MSG_MISSION_COUNT = 44
MSG_MISSION_CLEAR_ALL = 45
MSG_MISSION_ACK = 47
MSG_MISSION_REQUEST_INT = 51
MSG_MANUAL_CONTROL = 69
MSG_RC_CHANNELS_OVERRIDE = 70
MSG_MISSION_ITEM_INT = 73
MSG_COMMAND_INT = 75
MSG_COMMAND_LONG = 76
MSG_COMMAND_ACK = 77
MSG_TIMESYNC = 111
MSG_PARAM_EXT_REQUEST_READ = 320
MSG_PARAM_EXT_REQUEST_LIST = 321
MSG_PARAM_EXT_SET = 323

MESSAGE_NAMES = {
    MSG_HEARTBEAT: "HEARTBEAT",
    MSG_PING: "PING",
    MSG_PARAM_REQUEST_READ: "PARAM_REQUEST_READ",
    MSG_PARAM_REQUEST_LIST: "PARAM_REQUEST_LIST",
    MSG_PARAM_SET: "PARAM_SET",
    MSG_MISSION_REQUEST_LIST: "MISSION_REQUEST_LIST",
    MSG_MISSION_COUNT: "MISSION_COUNT",
    MSG_MISSION_CLEAR_ALL: "MISSION_CLEAR_ALL",
    MSG_MISSION_ACK: "MISSION_ACK",
    MSG_MISSION_REQUEST_INT: "MISSION_REQUEST_INT",
    MSG_MANUAL_CONTROL: "MANUAL_CONTROL",
    MSG_RC_CHANNELS_OVERRIDE: "RC_CHANNELS_OVERRIDE",
    MSG_MISSION_ITEM_INT: "MISSION_ITEM_INT",
    MSG_COMMAND_INT: "COMMAND_INT",
    MSG_COMMAND_LONG: "COMMAND_LONG",
    MSG_COMMAND_ACK: "COMMAND_ACK",
    MSG_TIMESYNC: "TIMESYNC",
    MSG_PARAM_EXT_REQUEST_READ: "PARAM_EXT_REQUEST_READ",
    MSG_PARAM_EXT_REQUEST_LIST: "PARAM_EXT_REQUEST_LIST",
    MSG_PARAM_EXT_SET: "PARAM_EXT_SET",
}

COMMAND_NAMES = {
    16: "NAV_WAYPOINT",
    20: "NAV_RETURN_TO_LAUNCH",
    21: "NAV_LAND",
    22: "NAV_TAKEOFF",
    115: "CONDITION_YAW",
    176: "DO_SET_MODE",
    178: "DO_CHANGE_SPEED",
    192: "DO_REPOSITION",
    195: "DO_SET_ROI_LOCATION",
    197: "DO_SET_ROI_NONE",
    201: "DO_SET_ROI",
    205: "DO_MOUNT_CONTROL",
    206: "DO_SET_CAM_TRIGG_DIST",
    224: "DO_SET_MISSION_CURRENT",
    262: "DO_SET_STANDARD_MODE",
    300: "MISSION_START",
    400: "COMPONENT_ARM_DISARM",
    410: "GET_HOME_POSITION",
    512: "REQUEST_MESSAGE",
    519: "REQUEST_PROTOCOL_VERSION",
    520: "REQUEST_AUTOPILOT_CAPABILITIES",
    521: "REQUEST_CAMERA_INFORMATION",
    525: "REQUEST_STORAGE_INFORMATION",
    527: "REQUEST_CAMERA_CAPTURE_STATUS",
    528: "REQUEST_FLIGHT_INFORMATION",
    2504: "REQUEST_VIDEO_STREAM_INFORMATION",
}

# Only messages that cannot directly move the aircraft or mutate a flight parameter are allowed
# from VSM -> RC during the bench dry-run. Mission upload is intentionally allowed: proving the
# uploaded bytes are identical is the purpose of this phase.
DRY_RUN_ALLOWED_MESSAGES = {
    MSG_HEARTBEAT,
    MSG_PING,
    MSG_PARAM_REQUEST_READ,
    MSG_PARAM_REQUEST_LIST,
    MSG_MISSION_REQUEST_LIST,
    MSG_MISSION_COUNT,
    MSG_MISSION_CLEAR_ALL,
    MSG_MISSION_ACK,
    MSG_MISSION_REQUEST_INT,
    MSG_MISSION_ITEM_INT,
    MSG_TIMESYNC,
    MSG_PARAM_EXT_REQUEST_READ,
    MSG_PARAM_EXT_REQUEST_LIST,
}

DRY_RUN_READ_ONLY_COMMANDS = {
    410,   # GET_HOME_POSITION
    512,   # REQUEST_MESSAGE
    519,   # REQUEST_PROTOCOL_VERSION
    520,   # REQUEST_AUTOPILOT_CAPABILITIES
    521,   # REQUEST_CAMERA_INFORMATION
    525,   # REQUEST_STORAGE_INFORMATION
    527,   # REQUEST_CAMERA_CAPTURE_STATUS
    528,   # REQUEST_FLIGHT_INFORMATION
    2504,  # REQUEST_VIDEO_STREAM_INFORMATION
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
    """Split one UDP datagram into MAVLink 2 frames and return undecodable bytes separately."""
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
            MAVLINK2_HEADER_BYTES
            + payload_len
            + 2
            + (MAVLINK2_SIGNATURE_BYTES if signed else 0)
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


def decode_frame(frame: MavlinkFrame) -> dict[str, Any]:
    """Decode only the fields needed for mission/wire validation."""
    data: dict[str, Any] = {
        "messageId": frame.message_id,
        "message": MESSAGE_NAMES.get(frame.message_id, f"MSG_{frame.message_id}"),
        "sequence": frame.sequence,
        "systemId": frame.system_id,
        "componentId": frame.component_id,
        "signed": frame.signed,
    }
    payload = _padded(frame.payload)

    if frame.message_id == MSG_MISSION_COUNT:
        data["count"] = struct.unpack_from("<H", payload, 0)[0]
        data["missionType"] = payload[4] if len(frame.payload) > 4 else 0
    elif frame.message_id == MSG_MISSION_REQUEST_INT:
        data["missionSeq"] = struct.unpack_from("<H", payload, 0)[0]
        data["targetSystem"] = payload[2]
        data["targetComponent"] = payload[3]
        data["missionType"] = payload[4] if len(frame.payload) > 4 else 0
    elif frame.message_id == MSG_MISSION_ITEM_INT:
        p1, p2, p3, p4 = struct.unpack_from("<ffff", payload, 0)
        x, y = struct.unpack_from("<ii", payload, 16)
        z = struct.unpack_from("<f", payload, 24)[0]
        mission_seq, command = struct.unpack_from("<HH", payload, 28)
        data.update(
            {
                "missionSeq": mission_seq,
                "command": command,
                "commandName": COMMAND_NAMES.get(command, f"MAV_CMD_{command}"),
                "frame": payload[34],
                "current": payload[35],
                "autocontinue": payload[36] if len(frame.payload) > 36 else 0,
                "param1": _json_float(p1),
                "param2": _json_float(p2),
                "param3": _json_float(p3),
                "param4": _json_float(p4),
                "latitude": x / 1e7,
                "longitude": y / 1e7,
                "altitude": _json_float(z),
            }
        )
    elif frame.message_id in {MSG_COMMAND_LONG, MSG_COMMAND_INT}:
        command = struct.unpack_from("<H", payload, 28)[0]
        data["command"] = command
        data["commandName"] = COMMAND_NAMES.get(command, f"MAV_CMD_{command}")
        if frame.message_id == MSG_COMMAND_LONG:
            data["params"] = [
                _json_float(value)
                for value in struct.unpack_from("<fffffff", payload, 0)
            ]
        else:
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
    elif frame.message_id == MSG_MISSION_ACK:
        data["targetSystem"] = payload[0]
        data["targetComponent"] = payload[1]
        data["result"] = payload[2]
        data["missionType"] = payload[3] if len(frame.payload) > 3 else 0
    elif frame.message_id == MSG_COMMAND_ACK:
        data["command"] = struct.unpack_from("<H", payload, 0)[0]
        data["result"] = payload[2]

    return data


def _command_id(frame: MavlinkFrame) -> int:
    return struct.unpack_from("<H", _padded(frame.payload), 28)[0]


def should_block_dry_run(frame: MavlinkFrame) -> tuple[bool, str | None]:
    """Fail closed: only an explicit read/upload allowlist is forwarded in dry-run."""
    if frame.message_id in {MSG_COMMAND_LONG, MSG_COMMAND_INT}:
        command = _command_id(frame)
        if command in DRY_RUN_READ_ONLY_COMMANDS:
            return False, None
        return True, COMMAND_NAMES.get(command, f"MAV_CMD_{command}")
    if frame.message_id in DRY_RUN_ALLOWED_MESSAGES:
        return False, None
    return True, MESSAGE_NAMES.get(frame.message_id, f"MSG_{frame.message_id}")


def dry_run_datagram_decision(datagram: bytes) -> tuple[bool, str | None]:
    """Block a whole datagram if any byte/frame is outside the dry-run allowlist."""
    frames, noise = split_mavlink2_frames(datagram)
    if not frames:
        return True, "NO_MAVLINK2_FRAME"
    if noise:
        return True, "UNDECODED_OR_MAVLINK1_BYTES"

    reasons: list[str] = []
    for frame in frames:
        blocked, reason = should_block_dry_run(frame)
        if blocked:
            reasons.append(reason or f"MSG_{frame.message_id}")
    if reasons:
        return True, ",".join(dict.fromkeys(reasons))
    return False, None


class JsonlRecorder:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")
        self._lock = threading.Lock()

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
        base: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "epochNs": time.time_ns(),
            "direction": direction,
            "source": f"{source[0]}:{source[1]}",
            "destination": f"{destination[0]}:{destination[1]}",
            "bytes": len(datagram),
            "blocked": blocked,
        }
        if block_reason:
            base["blockReason"] = block_reason

        rows: list[dict[str, Any]] = []
        rows.extend({**base, **decode_frame(frame), "rawHex": frame.raw.hex()} for frame in frames)
        if noise:
            rows.append({**base, "message": "UNDECODED_BYTES", "rawHex": noise.hex()})
        if not rows:
            rows.append({**base, "message": "EMPTY_DATAGRAM", "rawHex": ""})

        with self._lock:
            for row in rows:
                self._handle.write(json.dumps(row, separators=(",", ":")) + "\n")
            self._handle.flush()

    def close(self) -> None:
        with self._lock:
            if not self._handle.closed:
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

    def start(self) -> None:
        vsm = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        vsm.bind(self.listen)
        vsm.settimeout(0.5)

        aircraft = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        aircraft.bind(("0.0.0.0", self.aircraft_local_port))
        aircraft.settimeout(0.5)

        self._vsm_socket = vsm
        self._aircraft_socket = aircraft
        self._running.set()

        threads = [
            threading.Thread(target=self._pump_vsm_to_aircraft, daemon=True),
            threading.Thread(target=self._pump_aircraft_to_vsm, daemon=True),
        ]
        for worker in threads:
            worker.start()

        print(
            f"UgCS wiretap {self.listen[0]}:{self.listen[1]} -> "
            f"{self.rc[0]}:{self.rc[1]}"
        )
        print(f"Aircraft-side local UDP port: {aircraft.getsockname()[1]}")
        print(f"Safe dry-run: {'ON (fail-closed)' if self.safe_dry_run else 'OFF'}")
        try:
            while self._running.is_set():
                time.sleep(0.25)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
            for worker in threads:
                worker.join(timeout=1.0)

    def stop(self) -> None:
        self._running.clear()
        for sock in (self._vsm_socket, self._aircraft_socket):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        self.recorder.close()

    def _pump_vsm_to_aircraft(self) -> None:
        assert self._vsm_socket is not None
        assert self._aircraft_socket is not None
        while self._running.is_set():
            try:
                data, peer = self._vsm_socket.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return

            frames, noise = split_mavlink2_frames(data)
            valid_mavlink2 = bool(frames) and not noise
            blocked = False
            reason: str | None = None

            if self._vsm_peer is not None and peer != self._vsm_peer:
                blocked, reason = True, "UNEXPECTED_VSM_PEER"
            elif not valid_mavlink2:
                blocked, reason = True, "NON_MAVLINK2_OR_MALFORMED"
            elif self.safe_dry_run:
                blocked, reason = dry_run_datagram_decision(data)

            # Pin only a valid sender. In dry-run, a blocked state-changing packet cannot become
            # the authority-establishing first packet; an allowed heartbeat/mission message can.
            if self._vsm_peer is None and valid_mavlink2 and not blocked:
                self._vsm_peer = peer

            self.recorder.record(
                "VSM_TO_RC",
                peer,
                self.rc,
                data,
                blocked=blocked,
                block_reason=reason,
            )
            if not blocked:
                self._aircraft_socket.sendto(data, self.rc)

    def _pump_aircraft_to_vsm(self) -> None:
        assert self._vsm_socket is not None
        assert self._aircraft_socket is not None
        while self._running.is_set():
            try:
                data, peer = self._aircraft_socket.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return

            vsm_peer = self._vsm_peer
            if peer != self.rc:
                destination = vsm_peer or ("0.0.0.0", 0)
                self.recorder.record(
                    "RC_TO_VSM",
                    peer,
                    destination,
                    data,
                    blocked=True,
                    block_reason="UNEXPECTED_AIRCRAFT_PEER",
                )
                continue
            if vsm_peer is None:
                self.recorder.record(
                    "RC_TO_VSM",
                    peer,
                    ("0.0.0.0", 0),
                    data,
                    blocked=True,
                    block_reason="NO_PINNED_VSM_PEER",
                )
                continue

            self.recorder.record("RC_TO_VSM", peer, vsm_peer, data)
            self._vsm_socket.sendto(data, vsm_peer)


def load_wiretap_mission(path: str | Path) -> list[dict[str, Any]]:
    """Return the latest forwarded VSM->RC MISSION_ITEM_INT sequence."""
    items: dict[int, dict[str, Any]] = {}
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("direction") != "VSM_TO_RC":
                continue
            if row.get("message") == "MISSION_COUNT" and not row.get("blocked"):
                items = {}
            elif row.get("message") == "MISSION_ITEM_INT" and not row.get("blocked"):
                items[int(row["missionSeq"])] = row
    return [items[index] for index in sorted(items)]


def _float32_bytes(value: Any) -> bytes:
    if str(value).lower() == "nan":
        return struct.pack("<I", 0x7FC00000)
    return struct.pack("<f", float(value))


def mission_digest(items: list[dict[str, Any]], *, wire: bool) -> str:
    """Same canonical SHA-256 input used by Lyrebird's missionPlanDigest()."""
    digest = hashlib.sha256()
    for item in items:
        seq_key = "missionSeq" if wire else "seq"
        for key in ("param1", "param2", "param3", "param4"):
            digest.update(_float32_bytes(item.get(key, 0.0)))
        digest.update(struct.pack("<i", round(float(item.get("latitude", 0.0)) * 1e7)))
        digest.update(struct.pack("<i", round(float(item.get("longitude", 0.0)) * 1e7)))
        digest.update(_float32_bytes(item.get("altitude", 0.0)))
        digest.update(struct.pack("<H", int(item.get(seq_key, 0)) & 0xFFFF))
        digest.update(struct.pack("<H", int(item.get("command", 0)) & 0xFFFF))
        digest.update(struct.pack("<B", int(item.get("frame", 0)) & 0xFF))
        digest.update(struct.pack("<B", 1 if bool(item.get("autocontinue")) else 0))
        digest.update(b"\x00")  # MAV_MISSION_TYPE_MISSION
    return digest.hexdigest()


def _numbers_equal(left: Any, right: Any, tolerance: float) -> bool:
    if left == right:
        return True
    if str(left).lower() == "nan" and str(right).lower() == "nan":
        return True
    try:
        return math.isclose(
            float(left),
            float(right),
            rel_tol=0.0,
            abs_tol=tolerance,
        )
    except (TypeError, ValueError):
        return False


def compare_wiretap_to_rc(
    wire_items: list[dict[str, Any]],
    rc_trace: dict[str, Any],
    *,
    float_tolerance: float = 1e-4,
) -> dict[str, Any]:
    """Compare actual UgCS wire items with the exact mission Lyrebird accepted."""
    rc_items = list(rc_trace.get("items") or [])
    differences: list[str] = []
    if len(wire_items) != len(rc_items):
        differences.append(f"item count differs: wire={len(wire_items)} rc={len(rc_items)}")

    for index in range(min(len(wire_items), len(rc_items))):
        wire_item = wire_items[index]
        rc_item = rc_items[index]
        prefix = f"seq {wire_item.get('missionSeq', index)}"

        for wire_key, rc_key in (
            ("missionSeq", "seq"),
            ("command", "command"),
            ("frame", "frame"),
            ("autocontinue", "autocontinue"),
        ):
            left = wire_item.get(wire_key)
            right = rc_item.get(rc_key)
            if wire_key == "autocontinue":
                left, right = bool(left), bool(right)
            if left != right:
                differences.append(f"{prefix}: {wire_key} wire={left!r} rc={right!r}")

        for key in (
            "param1",
            "param2",
            "param3",
            "param4",
            "latitude",
            "longitude",
            "altitude",
        ):
            if not _numbers_equal(wire_item.get(key), rc_item.get(key), float_tolerance):
                differences.append(
                    f"{prefix}: {key} wire={wire_item.get(key)!r} rc={rc_item.get(key)!r}"
                )

    wire_digest = mission_digest(wire_items, wire=True)
    rc_digest = mission_digest(rc_items, wire=False)
    reported_digest = str(rc_trace.get("missionDigest") or "")

    if wire_digest != rc_digest:
        differences.append(
            f"mission digest differs: wire={wire_digest} rc={rc_digest}"
        )
    if reported_digest and reported_digest != rc_digest:
        differences.append(
            f"RC reported digest does not match its item trace: "
            f"reported={reported_digest} recomputed={rc_digest}"
        )

    return {
        "ok": not differences,
        "wireItems": len(wire_items),
        "rcItems": len(rc_items),
        "wireDigest": wire_digest,
        "rcDigest": rc_digest,
        "reportedRcDigest": reported_digest or None,
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
    result = compare_wiretap_to_rc(load_wiretap_mission(path), trace)
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
        help="Disable the dry-run allowlist and forward valid MAVLink 2 flight commands.",
    )
    parser.add_argument(
        "--compare",
        type=Path,
        metavar="WIRETAP_JSONL",
        help="Compare an existing capture with Lyrebird's currently accepted mission.",
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
