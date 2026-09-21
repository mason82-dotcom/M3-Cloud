"""Read-only Phase-10 GO/NO-GO gate for Lyrebird + UgCS."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lyrebird_groundstation.dji_client import DJIInterface
from lyrebird_groundstation.ugcs_wiretap import compare_wiretap_to_rc, load_wiretap_capture

POSITIONAL_COMMANDS = {16, 21, 22, 195}
MAV_CMD_DO_SET_ROI = 201
MAV_ROI_LOCATION = 3
MAV_FRAME_MISSION = 2
MAV_FRAME_GLOBAL_RELATIVE_ALT_INT = 6
SUPPORTED_PLATFORMS = {"M3E", "M3T", "M3M"}


@dataclass(frozen=True)
class PreflightPolicy:
    min_battery_percent: int = 50
    min_sd_free_mb: int = 2048
    max_rtk_age_ms: int = 3000
    max_snapshot_age_ms: int = 5000
    max_mission_age_ms: int = 120_000
    allow_rtk_float: bool = False


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str

    @property
    def failed(self) -> bool:
        return self.status == "FAIL"


@dataclass
class PreflightReport:
    rc_host: str
    generated_at: str
    policy: PreflightPolicy
    checks: list[Check]
    facts: dict[str, Any]

    @property
    def go(self) -> bool:
        return not any(check.failed for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "decision": "GO" if self.go else "NO-GO",
            "rcHost": self.rc_host,
            "generatedAt": self.generated_at,
            "policy": asdict(self.policy),
            "facts": self.facts,
            "checks": [asdict(check) for check in self.checks],
        }


def _pass(name: str, detail: str) -> Check:
    return Check(name, "PASS", detail)


def _warn(name: str, detail: str) -> Check:
    return Check(name, "WARN", detail)


def _fail(name: str, detail: str) -> Check:
    return Check(name, "FAIL", detail)


def _bool_check(name: str, value: bool, ok: str, bad: str) -> Check:
    return _pass(name, ok) if value else _fail(name, bad)


def _item_requires_position_frame(item: dict[str, Any]) -> bool:
    command = int(item.get("command", -1))
    if command in POSITIONAL_COMMANDS:
        return True
    if command == MAV_CMD_DO_SET_ROI:
        try:
            return int(float(item.get("param1", 0))) == MAV_ROI_LOCATION
        except (TypeError, ValueError):
            return False
    return False


def _mission_frame_errors(items: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for item in items:
        seq = int(item.get("seq", -1))
        frame = int(item.get("frame", -1))
        valid = (
            frame == MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
            if _item_requires_position_frame(item)
            else frame in {MAV_FRAME_MISSION, MAV_FRAME_GLOBAL_RELATIVE_ALT_INT}
        )
        if not valid:
            errors.append(
                f"seq {seq}: frame {frame} incompatible with command {item.get('command')}"
            )
    return errors


def _rtk_fix_ok(fix: str, allow_float: bool) -> bool:
    normalized = fix.strip().upper()
    if normalized in {"FIXED", "FIXED_POINT", "RTK_FIXED"}:
        return True
    return allow_float and normalized in {"FLOAT", "RTK_FLOAT"}


def _snapshot_checks(
    snapshot: dict[str, Any],
    policy: PreflightPolicy,
    now_ms: int,
) -> tuple[list[Check], int]:
    snapshot_ts = int(snapshot.get("timestampEpochMs") or 0)
    snapshot_age = now_ms - snapshot_ts if snapshot_ts else 2**63 - 1
    freshness = (
        _pass("snapshot_fresh", f"RC snapshot age {snapshot_age} ms")
        if 0 <= snapshot_age <= policy.max_snapshot_age_ms
        else _fail("snapshot_fresh", f"RC snapshot stale/invalid: age={snapshot_age} ms")
    )
    core = [
        _bool_check(
            "aircraft_connected",
            bool(snapshot.get("aircraftConnected")),
            "Flight controller connected",
            "Flight controller not connected",
        ),
        _bool_check(
            "camera_connected",
            bool(snapshot.get("cameraConnected")),
            "Main camera connected",
            "Main camera not connected",
        ),
        _bool_check(
            "on_ground",
            not bool(snapshot.get("airborne")),
            "Aircraft reports on ground",
            "Aircraft reports airborne",
        ),
        _bool_check(
            "failsafe_clear",
            not bool(snapshot.get("failsafe")),
            "DJI failsafe clear",
            "DJI failsafe active",
        ),
        _bool_check(
            "compass_healthy",
            bool(snapshot.get("compassHealthy")),
            "Compass reports healthy",
            "Compass error reported",
        ),
        _bool_check(
            "mavlink_flight_allowed",
            bool(snapshot.get("mavlinkFlightAllowed")),
            "MAVLink flight gate enabled",
            "MAVLink flight gate disabled",
        ),
        _bool_check(
            "manual_override_clear",
            not bool(snapshot.get("manualOverrideActive")),
            "Manual override clear",
            "Manual override active",
        ),
        _bool_check(
            "rc_connected",
            bool(snapshot.get("rcConnected")),
            "Remote controller connected",
            "Remote controller disconnected",
        ),
        _bool_check(
            "airlink_connected",
            bool(snapshot.get("airLinkConnected")),
            "DJI AirLink connected",
            "DJI AirLink disconnected",
        ),
        _bool_check(
            "home_position",
            bool(snapshot.get("homeSet")),
            "Home position set",
            "Home position not set",
        ),
    ]
    takeoff = (
        _pass("dji_takeoff_ready", "DJI reports ready to take off")
        if bool(snapshot.get("readyToTakeoff"))
        else _fail(
            "dji_takeoff_ready",
            f"DJI takeoff blocked: {snapshot.get('takeoffBlockReason') or 'UNKNOWN'}",
        )
    )
    return [freshness, *core, takeoff], snapshot_ts


def _battery_storage_checks(
    snapshot: dict[str, Any],
    policy: PreflightPolicy,
) -> list[Check]:
    battery = int(snapshot.get("batteryPercent", -1))
    battery_check = (
        _pass("battery", f"{battery}% >= policy {policy.min_battery_percent}%")
        if battery >= policy.min_battery_percent
        else _fail("battery", f"{battery}% < policy {policy.min_battery_percent}%")
    )

    storage = dict(snapshot.get("storage") or {})
    selected = str(storage.get("selected") or "UNKNOWN").upper()
    free_mb = int(storage.get("freeMb", -1))
    return [
        battery_check,
        _bool_check(
            "sd_inserted",
            bool(storage.get("sdInserted")),
            "Camera SD card inserted",
            "Camera SD card not inserted",
        ),
        (
            _pass("storage_selected", "Camera storage is SDCARD")
            if selected == "SDCARD"
            else _fail("storage_selected", f"Camera storage is {selected}, expected SDCARD")
        ),
        (
            _pass("sd_free_space", f"{free_mb} MB >= policy {policy.min_sd_free_mb} MB")
            if free_mb >= policy.min_sd_free_mb
            else _fail("sd_free_space", f"{free_mb} MB < policy {policy.min_sd_free_mb} MB")
        ),
    ]


def _camera_platform_check(platform: str) -> Check:
    if platform in SUPPORTED_PLATFORMS:
        return _pass("camera_platform", f"Detected {platform}")
    return _fail("camera_platform", f"Unsupported/unknown camera platform: {platform}")


def _survey_profile_check(
    camera: dict[str, Any],
    platform: str,
    profile: Any,
) -> Check:
    if profile and bool(camera.get("surveyProfileSupported")):
        return _pass(
            "survey_capture_profile",
            f"{profile} supported by runtime source range",
        )
    return _fail(
        "survey_capture_profile",
        f"No supported survey profile for platform={platform}, profile={profile}",
    )


def _expected_platform_check(platform: str, expected: str | None) -> Check | None:
    if not expected:
        return None
    wanted = expected.upper()
    if platform == wanted:
        return _pass("expected_platform", f"Detected platform matches {wanted}")
    return _fail("expected_platform", f"Expected {wanted}, detected {platform}")


def _expected_capture_profile_check(
    profile: Any,
    expected: str | None,
) -> Check | None:
    if not expected:
        return None
    wanted = expected.upper()
    actual = str(profile or "").upper()
    if actual == wanted:
        return _pass("expected_capture_profile", f"Capture profile matches {wanted}")
    return _fail(
        "expected_capture_profile",
        f"Expected {wanted}, selected {actual or 'NONE'}",
    )


def _camera_gimbal_checks(
    snapshot: dict[str, Any],
    expected_platform: str | None,
    expected_capture_profile: str | None,
) -> list[Check]:
    gimbal = dict(snapshot.get("gimbal") or {})
    camera = dict(snapshot.get("camera") or {})
    platform = str(camera.get("platform") or "OTHER").upper()
    profile = camera.get("surveyProfile")

    checks = [
        _bool_check(
            "gimbal_telemetry",
            bool(gimbal.get("valid")),
            "Raw gimbal telemetry valid",
            "Raw gimbal telemetry unavailable/invalid",
        ),
        _camera_platform_check(platform),
        _survey_profile_check(camera, platform, profile),
    ]
    optional = (
        _expected_platform_check(platform, expected_platform),
        _expected_capture_profile_check(profile, expected_capture_profile),
    )
    checks.extend(check for check in optional if check is not None)
    return checks


def _rtk_check(snapshot: dict[str, Any], policy: PreflightPolicy) -> Check:
    rtk = dict(snapshot.get("rtk") or {})
    fix = str(rtk.get("fix") or "UNKNOWN")
    age_raw = rtk.get("ageMs")
    age_ms = int(age_raw) if age_raw is not None else 2**63 - 1

    if not bool(rtk.get("enabled")):
        return _fail("rtk", "RTK disabled")
    if not bool(rtk.get("connected")):
        return _fail("rtk", "RTK module disconnected")
    if not bool(rtk.get("healthy")):
        return _fail("rtk", f"RTK unhealthy (fix={fix})")
    if age_ms > policy.max_rtk_age_ms:
        return _fail("rtk", f"RTK stale: {age_ms} ms > {policy.max_rtk_age_ms} ms")
    if not _rtk_fix_ok(fix, policy.allow_rtk_float):
        required = "FIXED or FLOAT" if policy.allow_rtk_float else "FIXED"
        return _fail("rtk", f"RTK fix={fix}; policy requires {required}")
    return _pass("rtk", f"RTK {fix}, connected/healthy, age {age_ms} ms")


def _mission_trace_check(items: list[dict[str, Any]], declared: int) -> Check:
    if items and declared == len(items):
        return _pass("mission_trace", f"Accepted mission contains {len(items)} items")
    return _fail(
        "mission_trace",
        f"Mission trace incomplete: declared={declared}, items={len(items)}",
    )


def _mission_frames_check(items: list[dict[str, Any]]) -> Check:
    frame_errors = _mission_frame_errors(items)
    if not frame_errors:
        return _pass("mission_frames", "All mission-item frames are Lyrebird-compatible")
    return _fail("mission_frames", "; ".join(frame_errors[:5]))


def _mission_age_check(
    mission_trace: dict[str, Any],
    snapshot_ts: int,
    policy: PreflightPolicy,
) -> Check:
    uploaded_ms = int(mission_trace.get("uploadedAtEpochMs") or 0)
    mission_age = snapshot_ts - uploaded_ms if snapshot_ts and uploaded_ms else -1
    if 0 <= mission_age <= policy.max_mission_age_ms:
        return _pass("mission_fresh", f"Accepted mission age {mission_age} ms")
    return _fail(
        "mission_fresh",
        f"Accepted mission stale/unverifiable: age={mission_age} ms "
        f"(policy {policy.max_mission_age_ms} ms)",
    )


def _mission_checks(
    mission_trace: dict[str, Any] | None,
    snapshot_ts: int,
    policy: PreflightPolicy,
) -> list[Check]:
    if mission_trace is None:
        return [_fail("mission_trace", "No accepted Lyrebird mission trace")]

    items = list(mission_trace.get("items") or [])
    declared = int(mission_trace.get("count") or 0)
    return [
        _mission_trace_check(items, declared),
        _mission_frames_check(items),
        _mission_age_check(mission_trace, snapshot_ts, policy),
    ]


def _wiretap_checks(
    wiretap_path: Path | None,
    mission_trace: dict[str, Any] | None,
) -> tuple[list[Check], dict[str, Any] | None]:
    if wiretap_path is None:
        return [_fail("wiretap", "Phase-9 wiretap capture required")], None
    if not wiretap_path.is_file():
        return [_fail("wiretap", f"Wiretap file not found: {wiretap_path}")], None
    if mission_trace is None:
        return [_fail("wiretap", "Cannot compare wiretap without mission trace")], None

    try:
        capture = load_wiretap_capture(wiretap_path)
        result = compare_wiretap_to_rc(
            list(capture.get("items") or []),
            mission_trace,
            wire_metadata=capture,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return [_fail("wiretap", f"Wiretap could not be decoded: {exc}")], None

    checks = [
        (
            _pass(
                "wiretap",
                f"Wire/RC identical: {result['wireItems']} items, "
                f"planId={result.get('wirePlanId')}",
            )
            if result.get("ok")
            else _fail(
                "wiretap",
                "; ".join(result.get("differences", [])[:5]) or "Wiretap/RC comparison failed",
            )
        )
    ]
    clock_delta = result.get("clockDeltaMs")
    if clock_delta is not None and abs(int(clock_delta)) > 60_000:
        checks.append(
            _warn(
                "wiretap_clock",
                f"Ground-station/RC clocks differ by {int(clock_delta)} ms; "
                "digest/planId/accepted ACK remain the identity proof",
            )
        )
    return checks, result


def _airlink_observation(snapshot: dict[str, Any]) -> Check:
    quality = int(snapshot.get("airLinkQualityPercent", -1))
    if quality >= 0:
        return _pass("airlink_quality_observed", f"DJI AirLink quality {quality}%")
    return _warn("airlink_quality_observed", "DJI AirLink quality unavailable")


def evaluate_preflight(
    *,
    rc_host: str,
    snapshot: dict[str, Any],
    mission_trace: dict[str, Any] | None,
    wiretap_path: Path | None,
    policy: PreflightPolicy = PreflightPolicy(),
    expected_platform: str | None = None,
    expected_capture_profile: str | None = None,
    now_epoch_ms: int | None = None,
) -> PreflightReport:
    """Evaluate immutable RC facts. No command or setting write is issued."""
    now_ms = int(time.time() * 1000) if now_epoch_ms is None else int(now_epoch_ms)

    snapshot_checks, snapshot_ts = _snapshot_checks(snapshot, policy, now_ms)
    checks = [
        *snapshot_checks,
        *_battery_storage_checks(snapshot, policy),
        *_camera_gimbal_checks(snapshot, expected_platform, expected_capture_profile),
        _rtk_check(snapshot, policy),
        *_mission_checks(mission_trace, snapshot_ts, policy),
    ]
    wire_checks, wire_result = _wiretap_checks(wiretap_path, mission_trace)
    checks.extend(wire_checks)
    checks.append(_airlink_observation(snapshot))

    return PreflightReport(
        rc_host=rc_host,
        generated_at=datetime.now(timezone.utc).isoformat(),
        policy=policy,
        checks=checks,
        facts={
            "snapshot": snapshot,
            "missionTrace": mission_trace,
            "wiretapComparison": wire_result,
        },
    )


def _print_report(report: PreflightReport) -> None:
    print()
    print("=" * 72)
    print(f"LYREBIRD / UGCS PREFLIGHT: {'GO' if report.go else 'NO-GO'}")
    print("=" * 72)
    for check in report.checks:
        print(f"[{check.status:4}] {check.name:28} {check.detail}")
    print()
    print("DECISION:", "GO" if report.go else "NO-GO")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only Lyrebird/UgCS Phase-10 survey preflight gate."
    )
    parser.add_argument("--rc", default=os.getenv("LYREBIRD_RC"))
    parser.add_argument("--wiretap", type=Path)
    parser.add_argument("--expect-platform", choices=sorted(SUPPORTED_PLATFORMS))
    parser.add_argument("--expect-capture-profile")
    parser.add_argument("--min-battery", type=int, default=50)
    parser.add_argument("--min-sd-free-mb", type=int, default=2048)
    parser.add_argument("--max-rtk-age-ms", type=int, default=3000)
    parser.add_argument("--max-snapshot-age-ms", type=int, default=5000)
    parser.add_argument("--max-mission-age-s", type=float, default=120.0)
    parser.add_argument("--allow-rtk-float", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.rc:
        parser.error("--rc or LYREBIRD_RC is required")

    client = DJIInterface(args.rc, query_config_name=True)
    snapshot = client.getPreflightStatus()
    if snapshot is None:
        raise SystemExit("NO-GO: RC preflight endpoint unavailable")

    report = evaluate_preflight(
        rc_host=args.rc,
        snapshot=snapshot,
        mission_trace=client.getLatestMissionTrace(),
        wiretap_path=args.wiretap,
        policy=PreflightPolicy(
            min_battery_percent=args.min_battery,
            min_sd_free_mb=args.min_sd_free_mb,
            max_rtk_age_ms=args.max_rtk_age_ms,
            max_snapshot_age_ms=args.max_snapshot_age_ms,
            max_mission_age_ms=max(0, int(args.max_mission_age_s * 1000)),
            allow_rtk_float=args.allow_rtk_float,
        ),
        expected_platform=args.expect_platform,
        expected_capture_profile=args.expect_capture_profile,
    )

    data = report.as_dict()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Preflight report: {args.output}")

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        _print_report(report)
    raise SystemExit(0 if report.go else 2)


if __name__ == "__main__":
    main()
