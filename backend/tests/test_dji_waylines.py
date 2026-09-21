from pymavlink.dialects.v20 import common as mavlink_common

from app.dji.waylines import model_keys, start_wayline_point, wayline_list_item
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
    )

    assert item["id"] == "11111111-1111-1111-1111-111111111111"
    assert item["drone_model_key"] == "0-77-2"
    assert item["payload_model_keys"] == ["1-68-0"]
    assert item["template_types"] == [0]
    assert item["favorited"] is False
