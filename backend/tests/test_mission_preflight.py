import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.missions.preflight import evaluate_preflight
from app.vehicles.base import VehicleSnapshot


def mission(**overrides):
    now = datetime.now(timezone.utc)
    values = {
        "id": uuid.uuid4(),
        "status": "READY",
        "item_count": 2,
        "plan_json": {
            "schema_version": 1,
            "protocol": "MAVLINK_MISSION",
            "items": [
                {
                    "seq": 0,
                    "frame": 6,
                    "command": 16,
                    "param1": 0.0,
                    "param2": None,
                    "param3": 0.0,
                    "param4": None,
                    "latitude_deg": 49.0,
                    "longitude_deg": 8.0,
                    "altitude_m": 50.0,
                    "autocontinue": True,
                }
            ],
        },
        "aircraft_sn": "M3E-001",
        "updated_at": now,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def vehicle(
    *,
    mission_runtime=None,
    ready=True,
    fix="FIXED",
    failsafe=False,
    platform="M3E",
    capacity_percent=75,
    remain_flight_time_s=None,
    return_home_power_percent=None,
    landing_power_percent=None,
):
    telemetry = {
        "aircraft_state": {
            "failsafe": failsafe,
            "positioning": {
                "fix": fix,
                "rtk": {"fix": fix},
            },
        },
        "safety": {
            "ready_to_takeoff": ready,
            "manual_override": False,
        },
        "battery": {
            "capacity_percent": capacity_percent,
            "remain_flight_time_s": remain_flight_time_s,
            "return_home_power_percent": return_home_power_percent,
            "landing_power_percent": landing_power_percent,
        },
        "payload": {
            "platform": platform,
            "capture_profiles": {
                "M3E": ["M3E_MAPPING"],
                "M3T": ["M3T_WIDE", "M3T_THERMAL"],
                "M3M": ["M3M_RGB", "M3M_RGB_MULTISPECTRAL"],
            }.get(platform, []),
        },
    }
    if mission_runtime is not None:
        telemetry["mission"] = mission_runtime

    return VehicleSnapshot(
        id="vehicle:M3E-001",
        sn="M3E-001",
        name="M3E",
        model="M3E",
        source="lyrebird",
        online=True,
        telemetry=telemetry,
        sources=("lyrebird",),
    )


def test_preflight_passes_without_blockers_but_execution_stays_disabled():
    result = evaluate_preflight(mission(), vehicle())

    assert result["checks_passed"] is True
    assert result["blocking_count"] == 0
    assert result["execution_enabled"] is False
    assert any(
        item["code"] == "positioning" and item["level"] == "PASS"
        for item in result["checks"]
    )


def test_preflight_blocks_missing_aircraft_and_empty_plan():
    result = evaluate_preflight(
        mission(aircraft_sn=None, item_count=0, status="DRAFT"),
        None,
    )

    assert result["checks_passed"] is False
    assert result["blocking_count"] >= 2


def test_preflight_blocks_unverified_active_aircraft_mission():
    result = evaluate_preflight(
        mission(),
        vehicle(mission_runtime={"state": 3, "current_seq": 4}),
    )

    assert result["checks_passed"] is False
    check = next(
        item for item in result["checks"]
        if item["code"] == "aircraft_mission_runtime"
    )
    assert check["level"] == "BLOCK"
    assert check["details"]["runtime_plan_identity"] == "UNVERIFIED"


def test_preflight_warns_on_float_without_inventing_failure():
    result = evaluate_preflight(mission(), vehicle(fix="FLOAT"))

    assert result["checks_passed"] is True
    assert result["warning_count"] == 1
    assert any(
        item["code"] == "positioning" and item["level"] == "WARN"
        for item in result["checks"]
    )


def test_grid_preflight_blocks_camera_platform_or_executor_mismatch():
    planned = mission(
        preferred_executor="DJI_NATIVE",
        plan_json={
            **mission().plan_json,
            "planning": {
                "schema_version": 1,
                "planner": "M3_CLOUD_GRID",
                "platform": "M3M",
                "capture_profile": "M3M_RGB_MULTISPECTRAL",
                "planning_sensor": "MULTISPECTRAL_5MP_LIMITING_FOOTPRINT",
            },
        },
    )

    mismatch = evaluate_preflight(planned, vehicle(platform="M3E"))
    assert mismatch["checks_passed"] is False
    platform_check = next(
        item for item in mismatch["checks"]
        if item["code"] == "planner_platform"
    )
    assert platform_check["level"] == "BLOCK"

    matching = evaluate_preflight(planned, vehicle(platform="M3M"))
    assert matching["checks_passed"] is True
    assert any(
        item["code"] == "planner_capture_profile" and item["level"] == "PASS"
        for item in matching["checks"]
    )

    onboard = mission(
        preferred_executor="ONBOARD",
        plan_json=planned.plan_json,
    )
    wrong_executor = evaluate_preflight(onboard, vehicle(platform="M3M"))
    assert wrong_executor["checks_passed"] is False
    assert any(
        item["code"] == "planner_executor" and item["level"] == "BLOCK"
        for item in wrong_executor["checks"]
    )

def test_grid_preflight_uses_dji_remaining_time_and_power_thresholds():
    planned = mission(
        preferred_executor="DJI_NATIVE",
        plan_json={
            **mission().plan_json,
            "planning": {
                "schema_version": 1,
                "planner": "M3_CLOUD_GRID",
                "platform": "M3E",
                "capture_profile": "M3E_MAPPING",
                "planning_sensor": "RGB_WIDE_20MP",
                "derived": {
                    "nominal_route_time_s": 600.0,
                },
            },
        },
    )

    comfortable = evaluate_preflight(
        planned,
        vehicle(
            remain_flight_time_s=900,
            return_home_power_percent=25,
            landing_power_percent=10,
        ),
    )
    assert comfortable["checks_passed"] is True
    assert any(
        item["code"] == "planner_flight_time" and item["level"] == "PASS"
        for item in comfortable["checks"]
    )
    assert any(
        item["code"] == "battery_power_margin" and item["level"] == "PASS"
        for item in comfortable["checks"]
    )

    tight = evaluate_preflight(
        planned,
        vehicle(
            remain_flight_time_s=650,
            return_home_power_percent=70,
            landing_power_percent=10,
        ),
    )
    assert tight["checks_passed"] is True
    assert any(
        item["code"] == "planner_flight_time" and item["level"] == "WARN"
        for item in tight["checks"]
    )
    assert any(
        item["code"] == "battery_power_margin" and item["level"] == "WARN"
        for item in tight["checks"]
    )

    insufficient = evaluate_preflight(
        planned,
        vehicle(
            capacity_percent=20,
            remain_flight_time_s=500,
            return_home_power_percent=25,
            landing_power_percent=10,
        ),
    )
    assert insufficient["checks_passed"] is False
    assert any(
        item["code"] == "planner_flight_time" and item["level"] == "BLOCK"
        for item in insufficient["checks"]
    )
    assert any(
        item["code"] == "battery_power_margin" and item["level"] == "BLOCK"
        for item in insufficient["checks"]
    )

    forced_landing = evaluate_preflight(
        planned,
        vehicle(
            capacity_percent=9,
            remain_flight_time_s=900,
            return_home_power_percent=25,
            landing_power_percent=10,
        ),
    )
    assert forced_landing["checks_passed"] is False
    check = next(
        item for item in forced_landing["checks"]
        if item["code"] == "battery_power_margin"
    )
    assert check["level"] == "BLOCK"
    assert "forced-landing" in check["message"]

def test_grid_preflight_prefers_total_time_when_reference_transit_is_planned():
    planned = mission(
        preferred_executor="DJI_NATIVE",
        plan_json={
            **mission().plan_json,
            "planning": {
                "schema_version": 1,
                "planner": "M3_CLOUD_GRID",
                "platform": "M3E",
                "capture_profile": "M3E_MAPPING",
                "planning_sensor": "RGB_WIDE_20MP",
                "derived": {
                    "nominal_route_time_s": 400.0,
                    "nominal_total_time_s": 700.0,
                },
            },
        },
    )

    result = evaluate_preflight(
        planned,
        vehicle(
            remain_flight_time_s=650,
            return_home_power_percent=25,
            landing_power_percent=10,
        ),
    )
    check = next(
        item for item in result["checks"]
        if item["code"] == "planner_flight_time"
    )
    assert check["level"] == "BLOCK"
    assert check["details"]["scope"] == "GRID_PLUS_REFERENCE_TRANSIT"
    assert check["details"]["required_time_s"] == 700.0

