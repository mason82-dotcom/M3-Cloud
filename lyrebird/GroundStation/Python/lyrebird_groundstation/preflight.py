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
    checks: list[Check] = []
    now_ms = int(time.time() * 1000) if now_epoch_ms is None else int(now_epoch_ms)
    snapshot_ts = int(snapshot.get("timestampEpochMs") or 0)
    snapshot_age = now_ms - snapshot_ts if snapshot_ts else 2**63 - 1
    checks.append(
        _pass("snapshot_fresh", f"RC snapshot age {snapshot_age} ms")
        if 0 <= snapshot_age <= policy.max_snapshot_age_ms
        else _fail("snapshot_fresh", f"RC snapshot stale/invalid: age={snapshot_age} ms")
    )

    for name, value, ok, bad in (
        ("aircraft_connected", bool(snapshot.get("aircraftConnected")), "Flight controller connected", "Flight controller not connected"),
        ("camera_connected", bool(snapshot.get("cameraConnected")), "Main camera connected", "Main camera not connected"),
        ("on_ground", not bool(snapshot.get("airborne")), "Aircraft reports on ground", "Aircraft reports airborne"),
        ("failsafe_clear", not bool(snapshot.get("failsafe")), "DJI failsafe clear", "DJI failsafe active"),
        ("compass_healthy", bool(snapshot.get("compassHealthy")), "Compass reports healthy", "Compass error reported"),
        ("mavlink_flight_allowed", bool(snapshot.get("mavlinkFlightAllowed")), "MAVLink flight gate enabled", "MAVLink flight gate disabled"),
        ("manual_override_clear", not bool(snapshot.get("manualOverrideActive")), "Manual override clear", "Manual override active"),
        ("rc_connected", bool(snapshot.get("rcConnected")), "Remote controller connected", "Remote controller disconnected"),
        ("airlink_connected", bool(snapshot.get("airLinkConnected")), "DJI AirLink connected", "DJI AirLink disconnected"),
        ("home_position", bool(snapshot.get("homeSet")), "Home position set", "Home position not set"),
    ):
        checks.append(_bool_check(name, value, ok, bad))

    checks.append(
        _pass("dji_takeoff_ready", "DJI reports ready to take off")
        if bool(snapshot.get("readyToTakeoff"))
        else _fail(
            "dji_takeoff_ready",
            f"DJI takeoff blocked: {snapshot.get('takeoffBlockReason') or 'UNKNOWN'}",
        )
    )

    battery = int(snapshot.get("batteryPercent", -1))
    checks.append(
        _pass("battery", f"{battery}% >= policy {policy.min_battery_percent}%")
        if battery >= policy.min_battery_percent
        else _fail("battery", f"{battery}% < policy {policy.min_battery_percent}%")
    )

    storage = dict(snapshot.get("storage") or {})
    checks.append(
        _bool_check(
            "sd_inserted",
            bool(storage.get("sdInserted")),
            "Camera SD card inserted",
            "Camera SD card not inserted",
        )
    )
    selected = str(storage.get("selected") or "UNKNOWN").upper()
    checks.append(
        _pass("storage_selected", "Camera storage is SDCARD")
        if selected == "SDCARD"
        else _fail("storage_selected", f"Camera storage is {selected}, expected SDCARD")
    )
    free_mb = int(storage.get("freeMb", -1))
    checks.append(
        _pass("sd_free_space", f"{free_mb} MB >= policy {policy.min_sd_free_mb} MB")
        if free_mb >= policy.min_sd_free_mb
        else _fail("sd_free_space", f"{free_mb} MB < policy {policy.min_sd_free_mb} MB")
    )

    gimbal = dict(snapshot.get("gimbal") or {})
    checks.append(
        _bool_check(
            "gimbal_telemetry",
            bool(gimbal.get("valid")),
            "Raw gimbal telemetry valid",
            "Raw gimbal telemetry unavailable/invalid",
        )
    )

    camera = dict(snapshot.get("camera") or {})
    platform = str(camera.get("platform") or "OTHER").upper()
    profile = camera.get("surveyProfile")
    checks.append(
        _pass("camera_platform", f"Detected {platform}")
        if platform in SUPPORTED_PLATFORMS
        else _fail("camera_platform", f"Unsupported/unknown camera platform: {platform}")
    )
    checks.append(
        _pass("survey_capture_profile", f"{profile} supported by runtime source range")
        if profile and bool(camera.get("surveyProfileSupported"))
        else _fail(
            "survey_capture_profile",
            f"No supported survey profile for platform={platform}, profile={profile}",
        )
    )
    if expected_platform:
        wanted = expected_platform.upper()
        checks.append(
            _pass("expected_platform", f"Detected platform matches {wanted}")
            if platform == wanted
            else _fail("expected_platform", f"Expected {wanted}, detected {platform}")
        )
    if expected_capture_profile:
        wanted = expected_capture_profile.upper()
        actual = str(profile or "").upper()
        checks.append(
            _pass("expected_capture_profile", f"Capture profile matches {wanted}")
            if actual == wanted
            else _fail(
                "expected_capture_profile",
                f"Expected {wanted}, selected {actual or 'NONE'}",
            )
        )

    rtk = dict(snapshot.get("rtk") or {})
    fix = str(rtk.get("fix") or "UNKNOWN")
    age_raw = rtk.get("ageMs")
    age_ms = int(age_raw) if age_raw is not None else 2**63 - 1
    if not bool(rtk.get("enabled")):
        checks.append(_fail("rtk", "RTK disabled"))
    elif not bool(rtk.get("connected")):
        checks.append(_fail("rtk", "RTK module disconnected"))
    elif not bool(rtk.get("healthy")):
        checks.append(_fail("rtk", f"RTK unhealthy (fix={fix})"))
    elif age_ms > policy.max_rtk_age_ms:
        checks.append(_fail("rtk", f"RTK stale: {age_ms} ms > {policy.max_rtk_age_ms} ms"))
    elif not _rtk_fix_ok(fix, policy.allow_rtk_float):
        required = "FIXED or FLOAT" if policy.allow_rtk_float else "FIXED"
        checks.append(_fail("rtk", f"RTK fix={fix}; policy requires {required}"))
    else:
        checks.append(_pass("rtk", f"RTK {fix}, connected/healthy, age {age_ms} ms"))

    if mission_trace is None:
        checks.append(_fail("mission_trace", "No accepted Lyrebird mission trace"))
    else:
        items = list(mission_trace.get("items") or [])
        declared = int(mission_trace.get("count") or 0)
        checks.append(
            _pass("mission_trace", f"Accepted mission contains {len(items)} items")
            if items and declared == len(items)
            else _fail(
                "mission_trace",
                f"Mission trace incomplete: declared={declared}, items={len(items)}",
            )
        )
        frame_errors = _mission_frame_errors(items)
        checks.append(
            _pass("mission_frames", "All mission-item frames are Lyrebird-compatible")
            if not frame_errors
            else _fail("mission_frames", "; ".join(frame_errors[:5]))
        )
        uploaded_ms = int(mission_trace.get("uploadedAtEpochMs") or 0)
        mission_age = snapshot_ts - uploaded_ms if snapshot_ts and uploaded_ms else -1
        checks.append(
            _pass("mission_fresh", f"Accepted mission age {mission_age} ms")
            if 0 <= mission_age <= policy.max_mission_age_ms
            else _fail(
                "mission_fresh",
                f"Accepted mission stale/unverifiable: age={mission_age} ms "
                f"(policy {policy.max_mission_age_ms} ms)",
            )
        )

    wire_result: dict[str, Any] | None = None
    if wiretap_path is None:
        checks.append(_fail("wiretap", "Phase-9 wiretap capture required"))
    elif not wiretap_path.is_file():
        checks.append(_fail("wiretap", f"Wiretap file not found: {wiretap_path}"))
    elif mission_trace is None:
        checks.append(_fail("wiretap", "Cannot compare wiretap without mission trace"))
    else:
        try:
            capture = load_wiretap_capture(wiretap_path)
            wire_result = compare_wiretap_to_rc(
                list(capture.get("items") or []),
                mission_trace,
                wire_metadata=capture,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            checks.append(_fail("wiretap", f"Wiretap could not be decoded: {exc}"))
        else:
            checks.append(
                _pass(
                    "wiretap",
                    f"Wire/RC identical: {wire_result['wireItems']} items, "
                    f"planId={wire_result.get('wirePlanId')}",
                )
                if wire_result.get("ok")
                else _fail(
                    "wiretap",
                    "; ".join(wire_result.get("differences", [])[:5])
                    or "Wiretap/RC comparison failed",
                )
            )
            clock_delta = wire_result.get("clockDeltaMs")
            if clock_delta is not None and abs(int(clock_delta)) > 60_000:
                checks.append(
                    _warn(
                        "wiretap_clock",
                        f"Ground-station/RC clocks differ by {int(clock_delta)} ms; "
                        "digest/planId/accepted ACK remain the identity proof",
                    )
                )

    quality = int(snapshot.get("airLinkQualityPercent", -1))
    checks.append(
        _pass("airlink_quality_observed", f"DJI AirLink quality {quality}%")
        if quality >= 0
        else _warn("airlink_quality_observed", "DJI AirLink quality unavailable")
    )

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
