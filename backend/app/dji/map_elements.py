from __future__ import annotations

import uuid
from typing import Any, Mapping


_RESOURCE_GEOMETRY = {
    0: "Point",
    1: "LineString",
    2: "Polygon",
}


class DJIMapValidationError(ValueError):
    pass


def shared_group_id(workspace_id: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"m3cloud:dji-pilot-map:{workspace_id}:shared",
        )
    )


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DJIMapValidationError(f"{label} must be numeric")
    return float(value)


def _position(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) < 2:
        raise DJIMapValidationError(f"{label} must contain longitude and latitude")
    lon = _number(value[0], f"{label}.longitude")
    lat = _number(value[1], f"{label}.latitude")
    if not -180.0 <= lon <= 180.0:
        raise DJIMapValidationError(f"{label}.longitude is outside [-180, 180]")
    if not -90.0 <= lat <= 90.0:
        raise DJIMapValidationError(f"{label}.latitude is outside [-90, 90]")

    result = [lon, lat]
    if len(value) >= 3:
        result.append(_number(value[2], f"{label}.altitude"))
    return result


def validate_geojson_content(
    content: Mapping[str, Any],
    *,
    resource_type: int,
) -> dict[str, Any]:
    expected_geometry = _RESOURCE_GEOMETRY.get(resource_type)
    if expected_geometry is None:
        raise DJIMapValidationError("resource.type must be 0, 1, or 2")

    if content.get("type") != "Feature":
        raise DJIMapValidationError("map content.type must be Feature")

    geometry = content.get("geometry")
    if not isinstance(geometry, Mapping):
        raise DJIMapValidationError("map content.geometry must be an object")
    geometry_type = geometry.get("type")
    if geometry_type != expected_geometry:
        raise DJIMapValidationError(
            f"resource.type {resource_type} requires {expected_geometry} geometry"
        )

    coordinates = geometry.get("coordinates")
    normalized_coordinates: Any
    if geometry_type == "Point":
        normalized_coordinates = _position(coordinates, "Point")
    elif geometry_type == "LineString":
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise DJIMapValidationError("LineString requires at least two positions")
        normalized_coordinates = [
            _position(value, f"LineString[{index}]")
            for index, value in enumerate(coordinates)
        ]
    else:
        if not isinstance(coordinates, list) or not coordinates:
            raise DJIMapValidationError("Polygon requires at least one ring")
        rings: list[list[list[float]]] = []
        for ring_index, ring in enumerate(coordinates):
            if not isinstance(ring, list) or len(ring) < 4:
                raise DJIMapValidationError(
                    f"Polygon ring {ring_index} requires at least four positions"
                )
            normalized_ring = [
                _position(value, f"Polygon[{ring_index}][{index}]")
                for index, value in enumerate(ring)
            ]
            if normalized_ring[0][:2] != normalized_ring[-1][:2]:
                raise DJIMapValidationError(
                    f"Polygon ring {ring_index} must be closed"
                )
            rings.append(normalized_ring)
        normalized_coordinates = rings

    properties = content.get("properties")
    if properties is None:
        properties = {}
    if not isinstance(properties, Mapping):
        raise DJIMapValidationError("map content.properties must be an object")

    normalized_properties = dict(properties)
    color = normalized_properties.get("color")
    if color is not None:
        if (
            not isinstance(color, str)
            or len(color) != 7
            or not color.startswith("#")
        ):
            raise DJIMapValidationError("map color must use #RRGGBB")
        try:
            int(color[1:], 16)
        except ValueError as exc:
            raise DJIMapValidationError("map color must use #RRGGBB") from exc

    clamp = normalized_properties.get("clampToGround")
    if clamp is not None and not isinstance(clamp, bool):
        raise DJIMapValidationError("clampToGround must be boolean")

    return {
        "type": "Feature",
        "properties": normalized_properties,
        "geometry": {
            "type": expected_geometry,
            "coordinates": normalized_coordinates,
        },
    }


def map_element_resource(
    *,
    resource_type: int,
    content: Mapping[str, Any],
    user_name: str,
) -> dict[str, Any]:
    return {
        "type": resource_type,
        "user_name": user_name,
        "content": dict(content),
    }


def map_ws_event(
    event: str,
    *,
    element_id: str,
    group_id: str,
    name: str | None = None,
    resource: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": element_id,
        "group_id": group_id,
    }
    if name is not None:
        data["name"] = name
    if resource is not None:
        data["resource"] = dict(resource)
    return {
        "type": f"dji_map_{event}",
        "data": data,
    }
