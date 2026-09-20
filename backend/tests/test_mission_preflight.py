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


def vehicle(*, mission_runtime=None, ready=True, fix="FIXED", failsafe=False):
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
            "capacity_percent": 75,
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
