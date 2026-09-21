import pytest
from pymavlink.dialects.v20 import common as mavlink_common

from app.dji.waylines import (
    compile_mission_wayline,
    inspect_native_wayline_bytes,
    model_keys,
    start_wayline_point,
    validate_native_wayline_metadata,
    wayline_list_item,
)
from app.dji.wpml import WPMLCompileError
from app.missions.plans import normalize_plan


def plan(platform: str):
    return normalize_plan(
        [
            {
                "seq": 0,
                "frame": 6,
                "command": mavlink_common.MAV_CMD_NAV_WAYPOINT,
                "latitude_deg": 49.123,
                "longitude_deg": 8.456,
                "altitude_m": 50.0,
            },
            {
                "seq": 1,
                "frame": 6,
                "command": mavlink_common.MAV_CMD_NAV_WAYPOINT,
                "latitude_deg": 49.124,
                "longitude_deg": 8.457,
                "altitude_m": 50.0,
            },
            {
                "seq": 2,
                "frame": 6,
                "command": mavlink_common.MAV_CMD_NAV_RETURN_TO_LAUNCH,
                "latitude_deg": 0.0,
                "longitude_deg": 0.0,
                "altitude_m": 0.0,
            },
        ],
        planning={"platform": platform},
    )


def test_pilot_device_model_keys_keep_m3_payloads_separate():
    assert model_keys("M3E") == ("0-77-0", ["1-66-0"])
    assert model_keys("M3T") == ("0-77-1", ["1-67-0"])
    assert model_keys("M3M") == ("0-77-2", ["1-68-0"])


def test_start_point_uses_dji_schema_lontitude_spelling():
    value = start_wayline_point(plan("M3E"))
    assert value == {
        "start_latitude": 49.123,
        "start_lontitude": 8.456,
    }


def test_wayline_list_item_matches_pilot_shape_and_is_compileable():
    item = wayline_list_item(
        mission_id="11111111-1111-1111-1111-111111111111",
        name="Field A",
        plan=plan("M3M"),
        updated_at_ms=123456789,
        favorited=True,
    )

    assert item["id"] == "11111111-1111-1111-1111-111111111111"
    assert item["drone_model_key"] == "0-77-2"
    assert item["payload_model_keys"] == ["1-68-0"]
    assert item["template_types"] == [0]
    assert item["favorited"] is True


@pytest.mark.parametrize(
    ("platform", "drone_key", "payload_key"),
    [
        ("M3E", "0-77-0", "1-66-0"),
        ("M3T", "0-77-1", "1-67-0"),
        ("M3M", "0-77-2", "1-68-0"),
    ],
)
def test_native_kmz_identity_is_read_from_wpml(
    platform,
    drone_key,
    payload_key,
):
    artifact = compile_mission_wayline(
        plan(platform),
        name=f"native-{platform}",
    )
    inspection = inspect_native_wayline_bytes(artifact.kmz)

    assert inspection.drone_model_key == drone_key
    assert inspection.payload_model_keys == [payload_key]
    assert inspection.template_types == [0]
    assert inspection.start_wayline_point == {
        "start_latitude": 49.123,
        "start_lontitude": 8.456,
    }
    assert inspection.size_bytes == len(artifact.kmz)
    assert len(inspection.sha256) == 64


def test_native_kmz_callback_cannot_relabel_m3t_as_m3m():
    artifact = compile_mission_wayline(plan("M3T"), name="thermal")
    inspection = inspect_native_wayline_bytes(artifact.kmz)

    with pytest.raises(WPMLCompileError, match="aircraft metadata"):
        validate_native_wayline_metadata(
            inspection,
            drone_model_key="0-77-2",
            payload_model_keys=["1-68-0"],
            template_types=[0],
        )


def test_native_kmz_callback_cannot_swap_payload_family():
    artifact = compile_mission_wayline(plan("M3E"), name="rgb")
    inspection = inspect_native_wayline_bytes(artifact.kmz)

    with pytest.raises(WPMLCompileError, match="payload metadata"):
        validate_native_wayline_metadata(
            inspection,
            drone_model_key="0-77-0",
            payload_model_keys=["1-67-0"],
            template_types=[0],
        )
