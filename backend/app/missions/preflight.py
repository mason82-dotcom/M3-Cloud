from __future__ import annotations

from typing import Any

from app.missions.plans import compatibility
from app.models import Mission
from app.vehicles.base import VehicleSnapshot
from app.vehicles.payloads import AircraftPlatform, platform_from_explicit_model


def evaluate_preflight(
    mission: Mission,
    vehicle: VehicleSnapshot | None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(
        code: str,
        level: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        checks.append(
            {
                "code": code,
                "level": level,
                "message": message,
                "details": details or {},
            }
        )

    plan = mission.plan_json or {}
    compat = compatibility(plan)
    planning = plan.get("planning") if isinstance(plan.get("planning"), dict) else None

    if mission.status == "ARCHIVED":
        add("mission_status", "BLOCK", "Mission is archived.")
    elif mission.item_count <= 0:
        add("plan_items", "BLOCK", "Mission has no plan items.")
    else:
        add(
            "plan_items",
            "PASS",
            f"Mission contains {mission.item_count} plan items.",
        )

    if compat["lyrebird_mavlink_upload_compatible"]:
        add(
            "lyrebird_upload_shape",
            "PASS",
            "Plan commands fit the current Lyrebird MAVLink upload surface.",
        )
    else:
        add(
            "lyrebird_upload_shape",
            "WARN",
            "Plan contains commands the current Lyrebird MAVLink upload would reject.",
            {
                "unsupported_items": compat["lyrebird_unsupported_items"],
            },
        )

    if not mission.aircraft_sn:
        add("aircraft_assignment", "BLOCK", "No aircraft is assigned.")
        vehicle = None
    elif vehicle is None:
        add(
            "aircraft_presence",
            "BLOCK",
            "Assigned aircraft is not currently visible to M3-Cloud.",
            {"aircraft_sn": mission.aircraft_sn},
        )
    elif not vehicle.online:
        add(
            "aircraft_presence",
            "BLOCK",
            "Assigned aircraft is currently offline.",
            {"aircraft_sn": mission.aircraft_sn},
        )
    else:
        add(
            "aircraft_presence",
            "PASS",
            "Assigned aircraft is online.",
            {
                "aircraft_sn": mission.aircraft_sn,
                "model": vehicle.model,
                "sources": list(vehicle.sources or (vehicle.source,)),
            },
        )

    telemetry = (
        vehicle.telemetry
        if vehicle is not None and isinstance(vehicle.telemetry, dict)
        else {}
    )
    aircraft = (
        telemetry.get("aircraft_state")
        if isinstance(telemetry.get("aircraft_state"), dict)
        else {}
    )
    safety = (
        telemetry.get("safety")
        if isinstance(telemetry.get("safety"), dict)
        else {}
    )
    positioning = (
        aircraft.get("positioning")
        if isinstance(aircraft.get("positioning"), dict)
        else {}
    )
    rtk = (
        positioning.get("rtk")
        if isinstance(positioning.get("rtk"), dict)
        else {}
    )

    if planning is not None and planning.get("planner") == "M3_CLOUD_GRID":
        planned_platform = str(planning.get("platform") or "UNKNOWN").upper()
        planned_profile = str(planning.get("capture_profile") or "")
        payload = (
            telemetry.get("payload")
            if isinstance(telemetry.get("payload"), dict)
            else {}
        )
        telemetry_platform = str(payload.get("platform") or "UNKNOWN").upper()
        model_platform = (
            platform_from_explicit_model(vehicle.model).value
            if vehicle is not None
            else AircraftPlatform.UNKNOWN.value
        )
        actual_platform = (
            telemetry_platform
            if telemetry_platform != AircraftPlatform.UNKNOWN.value
            else model_platform
        )

        if actual_platform == AircraftPlatform.UNKNOWN.value:
            add(
                "planner_platform",
                "BLOCK",
                "Grid mission has camera-specific geometry but the assigned aircraft platform "
                "cannot be verified.",
                {
                    "planned_platform": planned_platform,
                    "capture_profile": planned_profile,
                },
            )
        elif actual_platform != planned_platform:
            add(
                "planner_platform",
                "BLOCK",
                f"Grid was planned for {planned_platform}, but assigned aircraft reports "
                f"{actual_platform}.",
                {
                    "planned_platform": planned_platform,
                    "actual_platform": actual_platform,
                    "capture_profile": planned_profile,
                },
            )
        else:
            add(
                "planner_platform",
                "PASS",
                f"Grid camera geometry matches assigned {actual_platform}.",
                {
                    "capture_profile": planned_profile,
                    "planning_sensor": planning.get("planning_sensor"),
                },
            )

        reported_profiles = payload.get("capture_profiles")
        if isinstance(reported_profiles, list) and planned_profile:
            if planned_profile not in reported_profiles:
                add(
                    "planner_capture_profile",
                    "BLOCK",
                    "Assigned aircraft does not report the capture profile used to plan this grid.",
                    {
                        "capture_profile": planned_profile,
                        "reported_profiles": reported_profiles,
                    },
                )
            else:
                add(
                    "planner_capture_profile",
                    "PASS",
                    f"Capture profile {planned_profile} is reported by the assigned aircraft.",
                )

        if mission.preferred_executor != "DJI_NATIVE":
            add(
                "planner_executor",
                "BLOCK",
                "Distance-triggered grid missions require the DJI_NATIVE executor.",
                {"preferred_executor": mission.preferred_executor},
            )
        else:
            add(
                "planner_executor",
                "PASS",
                "DJI_NATIVE executor is selected for distance-triggered capture.",
            )

    ready_to_takeoff = safety.get("ready_to_takeoff")
    if ready_to_takeoff is False:
        add(
            "ready_to_takeoff",
            "BLOCK",
            "Aircraft reports that it is not ready to take off.",
            {"reason": safety.get("takeoff_block_reason")},
        )
    elif ready_to_takeoff is True:
        add("ready_to_takeoff", "PASS", "Aircraft reports ready-to-takeoff.")
    elif vehicle is not None:
        add(
            "ready_to_takeoff",
            "INFO",
            "Ready-to-takeoff state is not available from the current telemetry.",
        )

    manual_override = safety.get("manual_override")
    if manual_override is True:
        add(
            "manual_override",
            "BLOCK",
            "RC/manual override is active.",
        )
    elif manual_override is False:
        add("manual_override", "PASS", "Manual override is not active.")

    failsafe = aircraft.get("failsafe")
    if failsafe is True:
        add("failsafe", "BLOCK", "Aircraft reports failsafe state.")
    elif failsafe is False:
        add("failsafe", "PASS", "Aircraft does not report failsafe.")

    fix = str(positioning.get("fix") or rtk.get("fix") or "UNKNOWN").upper()
    if fix == "FIXED":
        add("positioning", "PASS", "RTK FIXED is currently reported.")
    elif fix == "FLOAT":
        add("positioning", "WARN", "RTK FLOAT is currently reported.")
    elif fix == "SINGLE":
        add("positioning", "WARN", "Only a single GNSS fix is currently reported.")
    elif fix == "STALE":
        add("positioning", "WARN", "RTK information is stale.")
    elif vehicle is not None:
        add(
            "positioning",
            "WARN",
            "No authoritative FIX/FLOAT solution is currently available.",
            {
                "fix": fix,
                "convergence": positioning.get("convergence"),
            },
        )

    battery = (
        telemetry.get("battery")
        if isinstance(telemetry.get("battery"), dict)
        else {}
    )
    if battery.get("capacity_percent") is not None:
        add(
            "battery",
            "INFO",
            "Aircraft battery telemetry is available.",
            {
                "capacity_percent": battery.get("capacity_percent"),
                "remain_flight_time_s": battery.get("remain_flight_time_s"),
            },
        )

    runtime = (
        telemetry.get("mission")
        if isinstance(telemetry.get("mission"), dict)
        else {}
    )
    runtime_state = runtime.get("state")
    if runtime_state in (3, 4):
        add(
            "aircraft_mission_runtime",
            "BLOCK",
            "Aircraft reports an active or paused mission whose plan identity is not verified.",
            {
                "state_code": runtime_state,
                "current_seq": runtime.get("current_seq"),
                "runtime_plan_identity": "UNVERIFIED",
            },
        )
    elif runtime:
        add(
            "aircraft_mission_runtime",
            "INFO",
            "Aircraft mission runtime is visible but not linked to this persisted plan.",
            {
                "state_code": runtime_state,
                "current_seq": runtime.get("current_seq"),
                "runtime_plan_identity": "UNVERIFIED",
            },
        )

    blocking = [item for item in checks if item["level"] == "BLOCK"]
    warnings = [item for item in checks if item["level"] == "WARN"]

    return {
        "mission_id": str(mission.id),
        "aircraft_sn": mission.aircraft_sn,
        "checks_passed": not blocking,
        "blocking_count": len(blocking),
        "warning_count": len(warnings),
        "execution_enabled": False,
        "runtime_plan_identity": "UNVERIFIED",
        "checks": checks,
        "note": (
            "Preflight gates sealed mission handoff/upload. M3-Cloud does not expose mission "
            "start, pause, resume, land, RTH, or abort actions."
        ),
    }
