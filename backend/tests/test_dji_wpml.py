import io
import zipfile
from xml.etree import ElementTree as ET

import pytest
from pymavlink.dialects.v20 import common as mavlink_common

from app.dji.wpml import KML_NS, WPML_NS, WPMLCompileError, compile_wpml_kmz
from app.missions.plans import normalize_plan


def survey_plan(platform="M3T"):
    items = [
        {
            "seq": 0,
            "frame": 6,
            "command": mavlink_common.MAV_CMD_NAV_TAKEOFF,
            "latitude_deg": 49.0,
            "longitude_deg": 8.0,
            "altitude_m": 50.0,
        },
        {
            "seq": 1,
            "frame": 6,
            "command": mavlink_common.MAV_CMD_DO_CHANGE_SPEED,
            "param1": 1.0,
            "param2": 6.0,
            "latitude_deg": 0.0,
            "longitude_deg": 0.0,
            "altitude_m": 0.0,
        },
        {
            "seq": 2,
            "frame": 6,
            "command": mavlink_common.MAV_CMD_DO_GIMBAL_MANAGER_PITCHYAW,
            "param1": -90.0,
            "latitude_deg": 0.0,
            "longitude_deg": 0.0,
            "altitude_m": 0.0,
        },
        {
            "seq": 3,
            "frame": 6,
            "command": mavlink_common.MAV_CMD_NAV_WAYPOINT,
            "latitude_deg": 49.0,
            "longitude_deg": 8.0,
            "altitude_m": 50.0,
        },
        {
            "seq": 4,
            "frame": 6,
            "command": mavlink_common.MAV_CMD_DO_SET_CAM_TRIGG_DIST,
            "param1": 12.5,
            "latitude_deg": 0.0,
            "longitude_deg": 0.0,
            "altitude_m": 0.0,
        },
        {
            "seq": 5,
            "frame": 6,
            "command": mavlink_common.MAV_CMD_NAV_WAYPOINT,
            "latitude_deg": 49.001,
            "longitude_deg": 8.001,
            "altitude_m": 50.0,
        },
        {
            "seq": 6,
            "frame": 6,
            "command": mavlink_common.MAV_CMD_DO_SET_CAM_TRIGG_DIST,
            "param1": 0.0,
            "latitude_deg": 0.0,
            "longitude_deg": 0.0,
            "altitude_m": 0.0,
        },
        {
            "seq": 7,
            "frame": 6,
            "command": mavlink_common.MAV_CMD_NAV_RETURN_TO_LAUNCH,
            "latitude_deg": 0.0,
            "longitude_deg": 0.0,
            "altitude_m": 0.0,
        },
    ]
    return normalize_plan(items, planning={"platform": platform})


def read_member(kmz: bytes, name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(kmz)) as archive:
        return archive.read(name)


def test_wpml_compiler_is_deterministic_and_uses_required_paths():
    first = compile_wpml_kmz(survey_plan(), filename_stem="Survey 1")
    second = compile_wpml_kmz(survey_plan(), filename_stem="Survey 1")

    assert first.kmz == second.kmz
    assert first.filename == "Survey_1.kmz"
    assert first.platform == "M3T"
    assert first.finish_action == "goHome"
    assert first.waypoint_count == 2
    assert first.distance_trigger_groups == 1

    with zipfile.ZipFile(io.BytesIO(first.kmz)) as archive:
        assert archive.namelist() == ["wpmz/template.kml", "wpmz/waylines.wpml"]


def test_waylines_contains_m3t_identity_relative_height_gimbal_and_distance_capture():
    artifact = compile_wpml_kmz(survey_plan())
    root = ET.fromstring(read_member(artifact.kmz, "wpmz/waylines.wpml"))
    ns = {"kml": KML_NS, "wpml": WPML_NS}

    assert root.find(".//wpml:droneEnumValue", ns).text == "77"
    assert root.find(".//wpml:droneSubEnumValue", ns).text == "1"
    assert root.find(".//wpml:payloadEnumValue", ns).text == "67"
    assert root.find(".//wpml:executeHeightMode", ns).text == "relativeToStartPoint"
    assert root.find(".//wpml:finishAction", ns).text == "goHome"
    assert root.find(".//wpml:autoFlightSpeed", ns).text == "6.0"
    assert root.find(".//wpml:gimbalPitchRotateAngle", ns).text == "-90.0"
    assert root.find(".//wpml:actionTriggerType", ns).text == "multipleDistance"
    assert root.find(".//wpml:actionTriggerParam", ns).text == "12.5"
    assert root.find(".//wpml:actionActuatorFunc", ns).text in {"gimbalRotate", "takePhoto"}


@pytest.mark.parametrize(
    ("platform", "subtype", "payload"),
    [("M3E", "0", "66"), ("M3T", "1", "67"), ("M3M", "2", "68")],
)
def test_m3_platform_mapping(platform, subtype, payload):
    artifact = compile_wpml_kmz(survey_plan(platform))
    root = ET.fromstring(read_member(artifact.kmz, "wpmz/waylines.wpml"))
    ns = {"wpml": WPML_NS}
    assert root.find(".//wpml:droneSubEnumValue", ns).text == subtype
    assert root.find(".//wpml:payloadEnumValue", ns).text == payload


def test_unknown_command_fails_closed():
    plan = survey_plan()
    plan["items"][3]["command"] = 999999

    with pytest.raises(WPMLCompileError, match="not safely mapped"):
        compile_wpml_kmz(plan)
