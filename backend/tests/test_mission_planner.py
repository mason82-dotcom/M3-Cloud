import math

import pytest

from app.missions.planner import (
    build_grid_preview,
    default_profile_for,
    planner_profile_catalog,
)


def rectangle(
    *,
    latitude=49.0,
    longitude=8.0,
    width_m=200.0,
    height_m=100.0,
):
    earth = 6_378_137.0
    dlat = math.degrees(height_m / earth)
    dlon = math.degrees(width_m / (earth * math.cos(math.radians(latitude))))
    return [
        (latitude, longitude),
        (latitude, longitude + dlon),
        (latitude + dlat, longitude + dlon),
        (latitude + dlat, longitude),
    ]


def test_profile_catalog_stays_aligned_with_native_m3_survey_profiles():
    keys = {profile["key"] for profile in planner_profile_catalog()}
    assert keys == {"M3E_MAPPING", "M3T_WIDE", "M3M_RGB_MULTISPECTRAL"}
    assert default_profile_for("M3E").key == "M3E_MAPPING"
    assert default_profile_for("M3T").key == "M3T_WIDE"
    assert default_profile_for("M3M").key == "M3M_RGB_MULTISPECTRAL"


def test_m3e_2cm_grid_matches_camera_geometry_and_is_wire_ready():
    preview = build_grid_preview(
        platform="M3E",
        capture_profile="M3E_MAPPING",
        polygon=rectangle(),
        gsd_cm=2.0,
        forward_overlap_pct=80.0,
        side_overlap_pct=70.0,
        direction_deg=0.0,
        speed_mps=8.0,
    )

    geometry = preview["geometry"]
    assert geometry["altitude_m"] == pytest.approx(73.274, abs=0.02)
    assert geometry["footprint_width_m"] == pytest.approx(105.6, abs=0.02)
    assert geometry["footprint_height_m"] == pytest.approx(79.12, abs=0.02)
    assert geometry["trigger_distance_m"] == pytest.approx(15.824, abs=0.02)
    assert geometry["desired_line_spacing_m"] == pytest.approx(31.68, abs=0.02)
    assert preview["cadence"]["effective_speed_mps"] == 8.0
    assert preview["compatibility"]["wire_ready"] is True
    assert preview["plan"]["planning"]["platform"] == "M3E"
    assert preview["plan"]["planning"]["capture_profile"] == "M3E_MAPPING"
    assert preview["plan"]["planning"]["polygon"] == preview["input"]["polygon"]
    assert preview["plan"]["planning"]["derived"]["trigger_distance_m"] == pytest.approx(
        15.824, abs=0.02
    )

    commands = [item["command"] for item in preview["plan"]["items"]]
    assert commands[:3] == [22, 178, 1000]
    assert commands[-1] == 20
    assert commands.count(206) == geometry["capture_segment_count"] * 2
    assert preview["mission_item_count"] == 4 + geometry["capture_segment_count"] * 4
    assert preview["input"]["finish_action"] == "RTH"
    assert preview["plan"]["planning"]["parameters"]["finish_action"] == "RTH"
    assert geometry["expected_photos_upper_bound"] >= 1
    assert geometry["expected_media_assets_upper_bound"] == geometry["expected_photos_upper_bound"]
    assert geometry["nominal_route_time_s"] > geometry["nominal_capture_time_s"]


def test_each_grid_segment_has_trigger_start_and_stop_so_transits_do_not_capture():
    preview = build_grid_preview(
        platform="M3E",
        capture_profile=None,
        polygon=rectangle(width_m=300.0, height_m=200.0),
        gsd_cm=2.0,
        forward_overlap_pct=80.0,
        side_overlap_pct=70.0,
        direction_deg=90.0,
        speed_mps=8.0,
    )
    assert preview["plan"]["items"][-1]["command"] == 20
    items = preview["plan"]["items"][3:-1]
    assert len(items) % 4 == 0
    for offset in range(0, len(items), 4):
        start_wp, start_trigger, end_wp, stop_trigger = items[offset:offset + 4]
        assert start_wp["command"] == 16
        assert start_trigger["command"] == 206
        assert start_trigger["param1"] > 0
        assert end_wp["command"] == 16
        assert stop_trigger["command"] == 206
        assert stop_trigger["param1"] == 0




def test_auto_direction_reduces_travel_on_an_elongated_rectangle():
    polygon = rectangle(width_m=300.0, height_m=100.0)
    manual = build_grid_preview(
        platform="M3E",
        capture_profile="M3E_MAPPING",
        polygon=polygon,
        gsd_cm=2.0,
        forward_overlap_pct=80.0,
        side_overlap_pct=70.0,
        direction_deg=0.0,
        speed_mps=8.0,
        optimize_direction=False,
    )
    optimized = build_grid_preview(
        platform="M3E",
        capture_profile="M3E_MAPPING",
        polygon=polygon,
        gsd_cm=2.0,
        forward_overlap_pct=80.0,
        side_overlap_pct=70.0,
        direction_deg=0.0,
        speed_mps=8.0,
        optimize_direction=True,
    )

    assert optimized["optimization"]["enabled"] is True
    assert optimized["optimization"]["candidate_count"] > 1
    assert optimized["geometry"]["route_distance_m"] < manual["geometry"]["route_distance_m"]
    assert optimized["optimization"]["selected_direction_deg"] == pytest.approx(90.0, abs=0.2)
    assert optimized["plan"]["planning"]["parameters"]["optimize_direction"] is True
    assert optimized["plan"]["planning"]["parameters"]["direction_deg"] == pytest.approx(
        optimized["optimization"]["selected_direction_deg"]
    )


def test_reference_point_prefers_the_nearer_grid_entry_and_counts_rth_transit():
    polygon = rectangle(width_m=300.0, height_m=180.0)
    baseline = build_grid_preview(
        platform="M3E",
        capture_profile="M3E_MAPPING",
        polygon=polygon,
        gsd_cm=2.0,
        forward_overlap_pct=80.0,
        side_overlap_pct=70.0,
        direction_deg=90.0,
        speed_mps=8.0,
        optimize_direction=False,
    )
    waypoints = [item for item in baseline["plan"]["items"] if item["command"] == 16]
    reference = (
        waypoints[-1]["latitude_deg"],
        waypoints[-1]["longitude_deg"],
    )

    referenced = build_grid_preview(
        platform="M3E",
        capture_profile="M3E_MAPPING",
        polygon=polygon,
        gsd_cm=2.0,
        forward_overlap_pct=80.0,
        side_overlap_pct=70.0,
        direction_deg=90.0,
        speed_mps=8.0,
        optimize_direction=False,
        start_reference=reference,
    )

    referenced_waypoints = [
        item for item in referenced["plan"]["items"] if item["command"] == 16
    ]
    assert referenced["optimization"]["reference_used"] is True
    assert referenced["optimization"]["reversed_for_reference"] is True
    assert referenced_waypoints[0]["latitude_deg"] == pytest.approx(reference[0], abs=1e-9)
    assert referenced_waypoints[0]["longitude_deg"] == pytest.approx(reference[1], abs=1e-9)
    assert referenced["geometry"]["ingress_distance_m"] == pytest.approx(0.0, abs=1e-6)
    assert referenced["geometry"]["return_distance_m"] > 0.0
    assert referenced["geometry"]["total_planned_distance_m"] == pytest.approx(
        referenced["geometry"]["route_distance_m"]
        + referenced["geometry"]["ingress_distance_m"]
        + referenced["geometry"]["return_distance_m"]
    )
    assert referenced["geometry"]["nominal_total_time_s"] > referenced["geometry"]["nominal_route_time_s"]


def test_grid_finish_action_can_land_or_be_explicitly_disabled():
    land = build_grid_preview(
        platform="M3E",
        capture_profile="M3E_MAPPING",
        polygon=rectangle(),
        gsd_cm=2.0,
        forward_overlap_pct=80.0,
        side_overlap_pct=70.0,
        direction_deg=0.0,
        speed_mps=8.0,
        finish_action="LAND",
    )
    assert land["plan"]["items"][-1]["command"] == 21
    assert land["input"]["finish_action"] == "LAND"
    assert land["warnings"] == []

    no_action = build_grid_preview(
        platform="M3E",
        capture_profile="M3E_MAPPING",
        polygon=rectangle(),
        gsd_cm=2.0,
        forward_overlap_pct=80.0,
        side_overlap_pct=70.0,
        direction_deg=0.0,
        speed_mps=8.0,
        finish_action="NONE",
    )
    assert no_action["plan"]["items"][-1]["command"] == 206
    assert no_action["plan"]["items"][-1]["param1"] == 0
    assert no_action["input"]["finish_action"] == "NONE"
    assert any("No terminal RTL/LAND" in warning for warning in no_action["warnings"])

    with pytest.raises(ValueError, match="Finish action"):
        build_grid_preview(
            platform="M3E",
            capture_profile="M3E_MAPPING",
            polygon=rectangle(),
            gsd_cm=2.0,
            forward_overlap_pct=80.0,
            side_overlap_pct=70.0,
            direction_deg=0.0,
            speed_mps=8.0,
            finish_action="HOVER",
        )


def test_m3m_multispectral_uses_narrower_ms_footprint_and_two_second_cadence():
    preview = build_grid_preview(
        platform="M3M",
        capture_profile="M3M_RGB_MULTISPECTRAL",
        polygon=rectangle(),
        gsd_cm=2.0,
        forward_overlap_pct=80.0,
        side_overlap_pct=70.0,
        direction_deg=0.0,
        speed_mps=10.0,
    )
    geometry = preview["geometry"]
    cadence = preview["cadence"]

    assert geometry["altitude_m"] == pytest.approx(43.83, abs=0.05)
    assert geometry["trigger_distance_m"] == pytest.approx(7.824, abs=0.02)
    assert cadence["minimum_interval_s"] == 2.0
    assert cadence["max_camera_speed_mps"] == pytest.approx(3.912, abs=0.01)
    assert cadence["effective_speed_mps"] == pytest.approx(3.912, abs=0.01)
    assert cadence["speed_limited_by_camera"] is True
    assert geometry["stored_assets_per_exposure"] == 6
    assert geometry["expected_media_assets_upper_bound"] == (
        geometry["expected_photos_upper_bound"] * 6
    )
    assert preview["warnings"]


def test_profile_platform_mismatch_and_non_native_profiles_fail_closed():
    with pytest.raises(ValueError, match="belongs to M3E"):
        build_grid_preview(
            platform="M3T",
            capture_profile="M3E_MAPPING",
            polygon=rectangle(),
            gsd_cm=2.0,
            forward_overlap_pct=80.0,
            side_overlap_pct=70.0,
            direction_deg=0.0,
            speed_mps=5.0,
        )

    with pytest.raises(ValueError, match="Unsupported capture profile"):
        build_grid_preview(
            platform="M3T",
            capture_profile="M3T_THERMAL",
            polygon=rectangle(),
            gsd_cm=2.0,
            forward_overlap_pct=80.0,
            side_overlap_pct=70.0,
            direction_deg=0.0,
            speed_mps=5.0,
        )


def test_self_intersecting_polygon_is_rejected():
    bow_tie = [
        (49.0, 8.0),
        (49.001, 8.001),
        (49.0, 8.001),
        (49.001, 8.0),
    ]
    with pytest.raises(ValueError, match="self-intersects"):
        build_grid_preview(
            platform="M3E",
            capture_profile=None,
            polygon=bow_tie,
            gsd_cm=2.0,
            forward_overlap_pct=80.0,
            side_overlap_pct=70.0,
            direction_deg=0.0,
            speed_mps=8.0,
        )
