import struct

import pytest

from lyrebird_groundstation.ugcs_wiretap import (
    MAVLINK2_MAGIC,
    MSG_COMMAND_LONG,
    MSG_MISSION_ITEM_INT,
    MSG_PARAM_SET,
    MavlinkFrame,
    compare_wiretap_to_rc,
    decode_frame,
    dry_run_datagram_decision,
    mission_digest,
    should_block_dry_run,
    split_mavlink2_frames,
)


def frame(msg_id, payload=b"", *, seq=7, system=255, component=190):
    raw = bytearray(10 + len(payload) + 2)
    raw[0] = MAVLINK2_MAGIC
    raw[1] = len(payload)
    raw[4] = seq
    raw[5] = system
    raw[6] = component
    raw[7:10] = int(msg_id).to_bytes(3, "little")
    raw[10 : 10 + len(payload)] = payload
    return bytes(raw)


def mission_item_payload(command=206, seq=3, frame_id=6):
    payload = bytearray(37)
    struct.pack_into("<ffff", payload, 0, 15.8, 0.0, 0.0, float("nan"))
    struct.pack_into("<ii", payload, 16, int(49.1e7), int(8.6e7))
    struct.pack_into("<f", payload, 24, 74.8)
    struct.pack_into("<HH", payload, 28, seq, command)
    payload[32] = 1
    payload[33] = 1
    payload[34] = frame_id
    payload[35] = 0
    payload[36] = 1
    return bytes(payload)


def command_long_payload(command):
    payload = bytearray(33)
    struct.pack_into("<fffffff", payload, 0, *([0.0] * 7))
    struct.pack_into("<H", payload, 28, command)
    payload[30] = 1
    payload[31] = 1
    return bytes(payload)


def test_split_and_decode_mission_item_int():
    frames, noise = split_mavlink2_frames(frame(MSG_MISSION_ITEM_INT, mission_item_payload()))
    assert noise == b""
    assert len(frames) == 1
    decoded = decode_frame(frames[0])
    assert decoded["missionSeq"] == 3
    assert decoded["command"] == 206
    assert decoded["frame"] == 6
    assert decoded["param1"] == pytest.approx(15.8, abs=1e-5)
    assert decoded["param4"] == "NaN"
    assert decoded["latitude"] == pytest.approx(49.1)
    assert decoded["longitude"] == pytest.approx(8.6)


def test_dry_run_allows_mission_item_but_blocks_motion_command():
    mission = split_mavlink2_frames(frame(MSG_MISSION_ITEM_INT, mission_item_payload()))[0][0]
    start = split_mavlink2_frames(
        frame(MSG_COMMAND_LONG, command_long_payload(300))
    )[0][0]
    assert should_block_dry_run(mission) == (False, None)
    assert should_block_dry_run(start)[0] is True


def test_dry_run_is_fail_closed_for_param_write_unknown_and_noise():
    param_set = split_mavlink2_frames(frame(MSG_PARAM_SET, b"\x00" * 23))[0][0]
    unknown = split_mavlink2_frames(frame(999, b""))[0][0]
    assert should_block_dry_run(param_set)[0] is True
    assert should_block_dry_run(unknown)[0] is True
    assert dry_run_datagram_decision(b"not mavlink")[0] is True
    # MAVLink 1 starts with 0xFE and therefore cannot leak through the MAVLink-2-only dry run.
    assert dry_run_datagram_decision(b"\xfe\x00\x00\x00")[0] is True


def test_whole_datagram_is_blocked_if_one_frame_is_unsafe():
    safe = frame(MSG_MISSION_ITEM_INT, mission_item_payload())
    unsafe = frame(MSG_COMMAND_LONG, command_long_payload(400))
    blocked, reason = dry_run_datagram_decision(safe + unsafe)
    assert blocked is True
    assert "COMPONENT_ARM_DISARM" in (reason or "")


def test_mission_digest_matches_between_wire_and_rc_shapes():
    wire = [{
        "missionSeq": 0,
        "command": 206,
        "frame": 6,
        "autocontinue": 1,
        "param1": 15.8,
        "param2": 0.0,
        "param3": 0.0,
        "param4": "NaN",
        "latitude": 49.1,
        "longitude": 8.6,
        "altitude": 74.8,
    }]
    rc = [{
        "seq": 0,
        "command": 206,
        "frame": 6,
        "autocontinue": True,
        "param1": 15.8,
        "param2": 0.0,
        "param3": 0.0,
        "param4": "NaN",
        "latitude": 49.1,
        "longitude": 8.6,
        "altitude": 74.8,
    }]
    assert mission_digest(wire, wire=True) == mission_digest(rc, wire=False)


def test_wire_vs_rc_comparison_accepts_float32_noise_and_reported_digest():
    wire = [{
        "missionSeq": 0,
        "command": 206,
        "frame": 6,
        "autocontinue": 1,
        "param1": 15.800001,
        "param2": 0.0,
        "param3": 0.0,
        "param4": "NaN",
        "latitude": 49.1,
        "longitude": 8.6,
        "altitude": 74.800003,
    }]
    rc_items = [{
        "seq": 0,
        "command": 206,
        "frame": 6,
        "autocontinue": True,
        "param1": 15.8,
        "param2": 0.0,
        "param3": 0.0,
        "param4": "NaN",
        "latitude": 49.1,
        "longitude": 8.6,
        "altitude": 74.8,
    }]
    # Digest is byte-canonical, so use the exact float32-decoded wire values for the reported RC
    # identity in this test. Field comparison separately tolerates normal JSON float formatting.
    canonical_wire = [{**wire[0], "param1": struct.unpack("<f", struct.pack("<f", 15.8))[0],
                       "altitude": struct.unpack("<f", struct.pack("<f", 74.8))[0]}]
    rc_trace = {
        "items": rc_items,
        "missionDigest": mission_digest(rc_items, wire=False),
    }
    result = compare_wiretap_to_rc(canonical_wire, rc_trace)
    assert result["ok"] is True
    assert result["differences"] == []


def test_comparison_reports_frame_change():
    wire = [{
        "missionSeq": 0, "command": 206, "frame": 6, "autocontinue": 1,
        "param1": 15.8, "param2": 0.0, "param3": 0.0, "param4": "NaN",
        "latitude": 49.1, "longitude": 8.6, "altitude": 74.8,
    }]
    rc = {"items": [{**wire[0], "seq": 0, "frame": 2}]}
    rc["items"][0].pop("missionSeq")
    result = compare_wiretap_to_rc(wire, rc)
    assert result["ok"] is False
    assert any("frame" in diff for diff in result["differences"])
