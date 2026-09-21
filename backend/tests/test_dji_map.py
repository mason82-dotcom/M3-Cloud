import pytest

from app.dji.map_elements import (
    DJIMapValidationError,
    map_ws_event,
    shared_group_id,
    validate_geojson_content,
)
from app.dji.tsa import live_event_to_pilot


def test_shared_group_id_is_stable_per_workspace():
    workspace = "e3dea0f5-37f2-4d79-ae58-490af3228069"
    assert shared_group_id(workspace) == shared_group_id(workspace)
    assert shared_group_id(workspace) != shared_group_id(
        "11111111-1111-1111-1111-111111111111"
    )


def test_point_geometry_is_normalized_and_validated():
    content = validate_geojson_content(
        {
            "type": "Feature",
            "properties": {
                "color": "#0091FF",
                "clampToGround": False,
            },
            "geometry": {
                "type": "Point",
                "coordinates": [8.456, 49.123, 120.5],
            },
        },
        resource_type=0,
    )
    assert content["geometry"]["coordinates"] == [8.456, 49.123, 120.5]


def test_resource_type_must_match_geometry():
    with pytest.raises(DJIMapValidationError, match="requires LineString"):
        validate_geojson_content(
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Point",
                    "coordinates": [8.456, 49.123],
                },
            },
            resource_type=1,
        )


def test_polygon_must_be_closed():
    with pytest.raises(DJIMapValidationError, match="must be closed"):
        validate_geojson_content(
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [8.0, 49.0],
                            [8.1, 49.0],
                            [8.1, 49.1],
                            [8.0, 49.1],
                        ]
                    ],
                },
            },
            resource_type=2,
        )


def test_map_ws_events_use_dji_business_codes():
    event = map_ws_event(
        "element_create",
        element_id="element-id",
        group_id="group-id",
        name="POI",
        resource={
            "type": 0,
            "user_name": "M3-Cloud",
            "content": {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Point",
                    "coordinates": [8.456, 49.123],
                },
            },
        },
    )
    translated = live_event_to_pilot(event)

    assert translated["biz_code"] == "map_element_create"
    assert translated["data"]["id"] == "element-id"
    assert translated["data"]["group_id"] == "group-id"


@pytest.mark.parametrize(
    ("event_type", "biz_code"),
    [
        ("dji_map_element_create", "map_element_create"),
        ("dji_map_element_update", "map_element_update"),
        ("dji_map_element_delete", "map_element_delete"),
        ("dji_map_group_refresh", "map_group_refresh"),
    ],
)
def test_map_ws_translation_matches_dji_contract(event_type, biz_code):
    translated = live_event_to_pilot(
        {
            "type": event_type,
            "data": {"id": "element-id", "group_id": "group-id"},
        }
    )
    assert translated["biz_code"] == biz_code
