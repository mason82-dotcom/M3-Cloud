import json
import struct

from lyrebird_groundstation.ugcs_wiretap import (
    MAVLINK2_MAGIC,
    MSG_COMMAND_LONG,
    MSG_HEARTBEAT,
    MSG_MISSION_ACK,
    MSG_MISSION_COUNT,
    MSG_MISSION_ITEM_INT,
    MSG_PARAM_SET,
    MavlinkFrame,
    UgcsWiretapProxy,
    canonical_mission_item,
    compare_wiretap_to_rc,
    decode_frame,
    load_wiretap_capture,
    mission_digest,
    mission_plan_id,
    should_block_dry_run,
    should_block_dry_run_datagram,
    split_mavlink2_frames,
)


def frame(msg_id, payload=b"", *, seq=7, system=255, component=190):
    # CRC bytes are placeholders: the wiretap observes structure and never rewrites a frame.
    raw = bytearray(10 + len(payload) + 2)
    raw[0] = MAVLINK2_MAGIC
    raw[1] = len(payload)
    raw[4] = seq
    raw[5] = system
    raw[6] = component
    raw[7:10] = int(msg_id).to_bytes(3, "little")
    raw[10 : 10 + len(payload)] = payload
    return bytes(raw)


def mission_count_payload(count=1):
    payload = bytearray(5)
    struct.pack_into("<H", payload, 0, count)
    payload[2] = 1
    payload[3] = 1
    payload[4] = 0
    return bytes(payload)


def mission_item_payload(command=206, seq=3, frame_id=2):
    payload = bytearray(38)
    struct.pack_into("<ffff", payload, 0, 15.8, 0.0, 0.0, float("nan"))
    struct.pack_into("<ii", payload, 16, int(49.1e7), int(8.6e7))
    struct.pack_into("<f", payload, 24, 74.8)
    struct.pack_into("<HH", payload, 28, seq, command)
    payload[32] = 1
    payload[33] = 1
    payload[34] = frame_id
    payload[35] = 0
    payload[36] = 1
    payload[37] = 0
    return bytes(payload)


def command_long_payload(command):
    payload = bytearray(33)
    struct.pack_into("<fffffff", payload, 0, *([0.0] * 7))
    struct.pack_into("<H", payload, 28, command)
    payload[30] = 1
    payload[31] = 1
    return bytes(payload)


def mav_frame(msg_id, payload=b""):
    raw = frame(msg_id, payload)
    frames, noise = split_mavlink2_frames(raw)
    assert noise == b""
    return frames[0]


def test_split_and_decode_mission_item_int():
    raw = frame(MSG_MISSION_ITEM_INT, mission_item_payload())
    frames, noise = split_mavlink2_frames(raw)

    assert noise == b""
    assert len(frames) == 1
    decoded = decode_frame(frames[0])
    assert decoded["missionSeq"] == 3
    assert decoded["command"] == 206
    assert decoded["frame"] == 2
    assert decoded["param1"] == struct.unpack("<f", struct.pack("<f", 15.8))[0]
    assert decoded["param4"] == "NaN"
    assert decoded["latitudeE7"] == 491000000
    assert decoded["longitudeE7"] == 86000000


def test_safe_dry_run_is_fail_closed_for_noise_mavlink1_and_unknown_message():
    assert should_block_dry_run_datagram(b"not mavlink")[0] is True
    assert should_block_dry_run_datagram(b"\xfe\x00\x00")[0] is True
    assert should_block_dry_run(mav_frame(99999))[0] is True


def test_safe_dry_run_allows_mission_upload_but_blocks_zero_count_clear():
    assert should_block_dry_run(
        mav_frame(MSG_MISSION_COUNT, mission_count_payload(8))
    )[0] is False
    assert should_block_dry_run(
        mav_frame(MSG_MISSION_ITEM_INT, mission_item_payload())
    )[0] is False
    blocked, reason = should_block_dry_run(
        mav_frame(MSG_MISSION_COUNT, mission_count_payload(0))
    )
    assert blocked is True
    assert "clear" in reason.lower()


def test_safe_dry_run_blocks_direct_motion_unknown_commands_and_parameter_writes():
    mission_start = mav_frame(MSG_COMMAND_LONG, command_long_payload(300))
    unknown_command = mav_frame(MSG_COMMAND_LONG, command_long_payload(65000))
    param_set = mav_frame(MSG_PARAM_SET, b"\x00" * 23)

    assert should_block_dry_run(mission_start)[0] is True
    assert should_block_dry_run(unknown_command)[0] is True
    assert should_block_dry_run(param_set) == (True, "PARAM_SET")


def test_safe_dry_run_allows_only_explicit_non_motion_commands():
    request_message = mav_frame(MSG_COMMAND_LONG, command_long_payload(512))
    camera_request = mav_frame(MSG_COMMAND_LONG, command_long_payload(521))
    direct_camera_action = mav_frame(MSG_COMMAND_LONG, command_long_payload(2000))

    assert should_block_dry_run(request_message)[0] is False
    assert should_block_dry_run(camera_request)[0] is False
    assert should_block_dry_run(direct_camera_action)[0] is True


def test_one_unsafe_frame_blocks_the_entire_multi_frame_datagram():
    safe = frame(MSG_HEARTBEAT, b"\x00" * 9)
    unsafe = frame(MSG_COMMAND_LONG, command_long_payload(300))
    blocked, reason = should_block_dry_run_datagram(safe + unsafe)

    assert blocked is True
    assert "MISSION_START" in reason


def test_vsm_peer_is_pinned_after_first_structurally_valid_datagram(tmp_path):
    proxy = UgcsWiretapProxy(
        rc_host="127.0.0.1",
        output_path=tmp_path / "capture.jsonl",
    )
    try:
        assert proxy._accept_vsm_peer(("127.0.0.1", 30000), structurally_valid=False) is False
        assert proxy._accept_vsm_peer(("127.0.0.1", 30000), structurally_valid=True) is True
        assert proxy._accept_vsm_peer(("127.0.0.1", 30000), structurally_valid=True) is True
        assert proxy._accept_vsm_peer(("127.0.0.1", 30001), structurally_valid=True) is False
    finally:
        proxy.recorder.close()


def test_canonical_digest_matches_android_golden_vector():
    item = {
        "missionSeq": 0,
        "command": 16,
        "frame": 6,
        "autocontinue": True,
        "param1": 0.0,
        "param2": 0.0,
        "param3": 0.0,
        "param4": "NaN",
        "latitudeE7": 465180000,
        "longitudeE7": 65660000,
        "altitude": 30.0,
        "missionType": 0,
    }
    assert len(canonical_mission_item(item)) == 35
    assert mission_plan_id([item]) == 0xD495F750
    assert mission_digest([item]) == (
        "bf0057504ab1f82df000c728328e34ddbdf277efcc678a3c73e33fe99bd295ea"
    )


def test_wire_vs_rc_comparison_checks_fields_crc_and_sha256():
    exact_param1 = struct.unpack("<f", struct.pack("<f", 15.8))[0]
    exact_altitude = struct.unpack("<f", struct.pack("<f", 74.8))[0]
    wire = [
        {
            "missionSeq": 0,
            "command": 206,
            "frame": 2,
            "autocontinue": 1,
            "missionType": 0,
            "param1": exact_param1,
            "param2": 0.0,
            "param3": 0.0,
            "param4": "NaN",
            "latitudeE7": 491000000,
            "longitudeE7": 86000000,
            "latitude": 49.1,
            "longitude": 8.6,
            "altitude": exact_altitude,
            "epochNs": 123_000_000,
        }
    ]
    rc_items = [
        {
            "seq": 0,
            "command": 206,
            "frame": 2,
            "autocontinue": True,
            "param1": exact_param1,
            "param2": 0.0,
            "param3": 0.0,
            "param4": "NaN",
            "latitude": 49.1,
            "longitude": 8.6,
            "altitude": exact_altitude,
        }
    ]
    rc = {
        "items": rc_items,
        "planId": mission_plan_id(wire),
        "missionDigest": mission_digest(wire),
        "uploadedAtEpochMs": 130,
    }

    result = compare_wiretap_to_rc(wire, rc)
    assert result["ok"] is True
    assert result["wirePlanId"] == result["rcPlanId"]
    assert result["wireMissionDigest"] == result["rcMissionDigest"]
    assert result["clockDeltaMs"] == 7


def test_capture_loader_tracks_latest_upload_and_requires_accepted_ack(tmp_path):
    path = tmp_path / "wiretap.jsonl"
    rows = [
        {
            "direction": "VSM_TO_RC",
            "message": "MISSION_COUNT",
            "count": 1,
            "blocked": False,
            "epochNs": 10,
        },
        {
            "direction": "VSM_TO_RC",
            "message": "MISSION_ITEM_INT",
            "missionSeq": 0,
            "blocked": False,
            "epochNs": 20,
        },
        {
            "direction": "RC_TO_VSM",
            "message": "MISSION_ACK",
            "result": 0,
            "epochNs": 30,
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    capture = load_wiretap_capture(path)
    assert capture["expectedCount"] == 1
    assert capture["acceptedAck"] is True
    assert capture["ackEpochNs"] == 30
    assert [row["missionSeq"] for row in capture["items"]] == [0]


def test_compare_reports_incomplete_or_unacknowledged_latest_upload():
    wire = [
        {
            "missionSeq": 0,
            "command": 16,
            "frame": 6,
            "autocontinue": True,
            "param1": 0.0,
            "param2": 0.0,
            "param3": 0.0,
            "param4": "NaN",
            "latitudeE7": 465180000,
            "longitudeE7": 65660000,
            "latitude": 46.518,
            "longitude": 6.566,
            "altitude": 30.0,
        }
    ]
    rc = {
        "items": [
            {
                "seq": 0,
                "command": 16,
                "frame": 6,
                "autocontinue": True,
                "param1": 0.0,
                "param2": 0.0,
                "param3": 0.0,
                "param4": "NaN",
                "latitude": 46.518,
                "longitude": 6.566,
                "altitude": 30.0,
            }
        ],
        "planId": mission_plan_id(wire),
        "missionDigest": mission_digest(wire),
    }
    result = compare_wiretap_to_rc(
        wire,
        rc,
        wire_metadata={"expectedCount": 2, "acceptedAck": False},
    )
    assert result["ok"] is False
    assert any("incomplete" in diff for diff in result["differences"])
    assert any("MISSION_ACK" in diff for diff in result["differences"])
