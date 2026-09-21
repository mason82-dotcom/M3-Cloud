import json
from pathlib import Path

from lyrebird_groundstation.preflight import PreflightPolicy, evaluate_preflight
from lyrebird_groundstation.ugcs_wiretap import mission_digest, mission_plan_id

NOW = 1_000_000


def snapshot(**updates):
    data = {
        "timestampEpochMs": NOW,
        "aircraftConnected": True,
        "cameraConnected": True,
        "airborne": False,
        "failsafe": False,
        "compassHealthy": True,
        "mavlinkFlightAllowed": True,
        "manualOverrideActive": False,
        "readyToTakeoff": True,
        "takeoffBlockReason": "NONE",
        "batteryPercent": 78,
        "homeSet": True,
        "rcConnected": True,
        "airLinkConnected": True,
        "airLinkQualityPercent": 84,
        "storage": {"sdInserted": True, "selected": "SDCARD", "freeMb": 65536},
        "camera": {
            "cameraType": "M3E",
            "platform": "M3E",
            "surveyProfile": "M3E_MAPPING",
            "surveyProfileSupported": True,
        },
        "gimbal": {"valid": True},
        "rtk": {
            "enabled": True,
            "connected": True,
            "healthy": True,
            "fix": "FIXED",
            "ageMs": 250,
            "source": "CUSTOM_NETWORK_SERVICE",
        },
    }
    data.update(updates)
    return data


def mission_items():
    return [
        {
            "seq": 0,
            "command": 206,
            "frame": 2,
            "autocontinue": True,
            "param1": 15.8,
            "param2": 0.0,
            "param3": 0.0,
            "param4": "NaN",
            "latitude": 0.0,
            "longitude": 0.0,
            "altitude": 0.0,
            "missionType": 0,
        },
        {
            "seq": 1,
            "command": 16,
            "frame": 6,
            "autocontinue": True,
            "param1": 0.0,
            "param2": 0.0,
            "param3": 0.0,
            "param4": "NaN",
            "latitude": 49.1,
            "longitude": 8.6,
            "altitude": 74.8,
            "missionType": 0,
        },
        {
            "seq": 2,
            "command": 16,
            "frame": 6,
            "autocontinue": True,
            "param1": 0.0,
            "param2": 0.0,
            "param3": 0.0,
            "param4": "NaN",
            "latitude": 49.2,
            "longitude": 8.6,
            "altitude": 74.8,
            "missionType": 0,
        },
        {
            "seq": 3,
            "command": 206,
            "frame": 2,
            "autocontinue": True,
            "param1": 0.0,
            "param2": 0.0,
            "param3": 0.0,
            "param4": "NaN",
            "latitude": 0.0,
            "longitude": 0.0,
            "altitude": 0.0,
            "missionType": 0,
        },
    ]


def trace():
    items = mission_items()
    return {
        "available": True,
        "count": len(items),
        "planId": mission_plan_id(items),
        "missionDigest": mission_digest(items),
        "uploadedAtEpochMs": NOW - 10_000,
        "items": items,
    }


def wiretap(tmp_path: Path, items=None):
    items = mission_items() if items is None else items
    path = tmp_path / "wiretap.jsonl"
    rows = [
        {
            "direction": "VSM_TO_RC",
            "message": "MISSION_COUNT",
            "count": len(items),
            "blocked": False,
            "epochNs": (NOW - 12_000) * 1_000_000,
        }
    ]
    for item in items:
        rows.append(
            {
                **item,
                "direction": "VSM_TO_RC",
                "message": "MISSION_ITEM_INT",
                "missionSeq": item["seq"],
                "blocked": False,
                "epochNs": (NOW - 11_000 + item["seq"]) * 1_000_000,
            }
        )
    rows.append(
        {
            "direction": "RC_TO_VSM",
            "message": "MISSION_ACK",
            "result": 0,
            "epochNs": (NOW - 10_500) * 1_000_000,
        }
    )
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_all_required_gates_can_produce_go(tmp_path):
    report = evaluate_preflight(
        rc_host="rc",
        snapshot=snapshot(),
        mission_trace=trace(),
        wiretap_path=wiretap(tmp_path),
        expected_platform="M3E",
        expected_capture_profile="M3E_MAPPING",
        now_epoch_ms=NOW + 100,
    )
    assert report.go is True
    assert all(c.status != "FAIL" for c in report.checks)


def test_missing_wiretap_forces_no_go():
    report = evaluate_preflight(
        rc_host="rc",
        snapshot=snapshot(),
        mission_trace=trace(),
        wiretap_path=None,
        now_epoch_ms=NOW,
    )
    assert report.go is False
    assert any(c.name == "wiretap" and c.status == "FAIL" for c in report.checks)


def test_rtk_float_is_explicit_override():
    status = snapshot()
    status["rtk"] = {**status["rtk"], "fix": "FLOAT"}
    denied = evaluate_preflight(
        rc_host="rc",
        snapshot=status,
        mission_trace=trace(),
        wiretap_path=None,
        now_epoch_ms=NOW,
    )
    allowed = evaluate_preflight(
        rc_host="rc",
        snapshot=status,
        mission_trace=trace(),
        wiretap_path=None,
        policy=PreflightPolicy(allow_rtk_float=True),
        now_epoch_ms=NOW,
    )
    assert any(c.name == "rtk" and c.status == "FAIL" for c in denied.checks)
    assert any(c.name == "rtk" and c.status == "PASS" for c in allowed.checks)


def test_rtk_disconnected_is_no_go():
    status = snapshot()
    status["rtk"] = {**status["rtk"], "connected": False}
    report = evaluate_preflight(
        rc_host="rc",
        snapshot=status,
        mission_trace=trace(),
        wiretap_path=None,
        now_epoch_ms=NOW,
    )
    assert any(c.name == "rtk" and c.status == "FAIL" for c in report.checks)


def test_policy_thresholds_and_snapshot_age_are_hard_gates():
    status = snapshot(timestampEpochMs=NOW - 10_000, batteryPercent=49)
    status["storage"] = {**status["storage"], "freeMb": 1024}
    report = evaluate_preflight(
        rc_host="rc",
        snapshot=status,
        mission_trace=trace(),
        wiretap_path=None,
        policy=PreflightPolicy(min_battery_percent=50, min_sd_free_mb=2048),
        now_epoch_ms=NOW,
    )
    failed = {c.name for c in report.checks if c.status == "FAIL"}
    assert {"snapshot_fresh", "battery", "sd_free_space"} <= failed


def test_platforms_are_not_cross_mapped():
    status = snapshot()
    status["camera"] = {
        **status["camera"],
        "platform": "M3M",
        "cameraType": "M3M",
        "surveyProfile": "M3M_RGB_MULTISPECTRAL",
    }
    report = evaluate_preflight(
        rc_host="rc",
        snapshot=status,
        mission_trace=trace(),
        wiretap_path=None,
        expected_platform="M3E",
        expected_capture_profile="M3E_MAPPING",
        now_epoch_ms=NOW,
    )
    failed = {c.name for c in report.checks if c.status == "FAIL"}
    assert {"expected_platform", "expected_capture_profile"} <= failed


def test_invalid_raw_gimbal_and_failsafe_are_no_go():
    status = snapshot(failsafe=True)
    status["gimbal"] = {"valid": False}
    report = evaluate_preflight(
        rc_host="rc",
        snapshot=status,
        mission_trace=trace(),
        wiretap_path=None,
        now_epoch_ms=NOW,
    )
    failed = {c.name for c in report.checks if c.status == "FAIL"}
    assert {"failsafe_clear", "gimbal_telemetry"} <= failed


def test_stale_accepted_mission_is_no_go(tmp_path):
    mission = trace()
    mission["uploadedAtEpochMs"] = NOW - 300_000
    report = evaluate_preflight(
        rc_host="rc",
        snapshot=snapshot(),
        mission_trace=mission,
        wiretap_path=wiretap(tmp_path),
        now_epoch_ms=NOW,
    )
    assert any(c.name == "mission_fresh" and c.status == "FAIL" for c in report.checks)


def test_wiretap_mismatch_is_no_go(tmp_path):
    wrong = mission_items()
    wrong[1] = {**wrong[1], "altitude": 75.8}
    report = evaluate_preflight(
        rc_host="rc",
        snapshot=snapshot(),
        mission_trace=trace(),
        wiretap_path=wiretap(tmp_path, wrong),
        now_epoch_ms=NOW,
    )
    assert any(c.name == "wiretap" and c.status == "FAIL" for c in report.checks)
