from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


M3_PRODUCT_TYPE = 77
M3E_SUB_TYPE = 0
M3T_SUB_TYPE = 1
M3_MODELS: dict[int, str] = {
    M3E_SUB_TYPE: "DJI_MAVIC_3E",
    M3T_SUB_TYPE: "DJI_MAVIC_3T",
}

M3_WRITABLE_PROPERTIES = frozenset(
    {
        "obstacle_avoidance",
        "height_limit",
        "night_lights_state",
        "camera_watermark_settings",
    }
)

_OBSTACLE_KEYS = frozenset({"horizon", "upside", "downside"})
_WATERMARK_SWITCH_KEYS = frozenset(
    {
        "global_enable",
        "drone_type_enable",
        "drone_sn_enable",
        "datetime_enable",
        "gps_enable",
        "user_custom_string_enable",
    }
)
_WATERMARK_KEYS = _WATERMARK_SWITCH_KEYS | {"user_custom_string", "layout"}


class M3ThingModelValidationError(ValueError):
    """Raised when a property patch violates the DJI M3 Pilot thing model."""


def is_m3_identity(product_type: object, sub_type: object) -> bool:
    return (
        isinstance(product_type, int)
        and not isinstance(product_type, bool)
        and product_type == M3_PRODUCT_TYPE
        and isinstance(sub_type, int)
        and not isinstance(sub_type, bool)
        and sub_type in M3_MODELS
    )


def m3_model_name(sub_type: int) -> str:
    try:
        return M3_MODELS[sub_type]
    except KeyError as exc:
        raise M3ThingModelValidationError(
            f"unsupported M3 subtype: {sub_type!r}"
        ) from exc


def _integer(value: Any, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise M3ThingModelValidationError(f"{name} must be an integer")
    return value


def _binary_switch(value: Any, *, name: str) -> int:
    number = _integer(value, name=name)
    if number not in (0, 1):
        raise M3ThingModelValidationError(f"{name} must be 0 or 1")
    return number


def _validate_obstacle_avoidance(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping) or not value:
        raise M3ThingModelValidationError(
            "obstacle_avoidance must be a non-empty object"
        )

    keys = set(value)
    unknown = keys - _OBSTACLE_KEYS
    missing = _OBSTACLE_KEYS - keys
    if unknown:
        raise M3ThingModelValidationError(
            f"obstacle_avoidance contains unsupported fields: {sorted(unknown)}"
        )
    if missing:
        # DJI exposes obstacle_avoidance as one rw struct. Requiring the full
        # struct prevents an omitted direction from being implicitly reset by
        # firmware that treats property/set as replacement rather than patch.
        raise M3ThingModelValidationError(
            f"obstacle_avoidance requires all directions: {sorted(missing)}"
        )

    return {
        key: _binary_switch(value[key], name=f"obstacle_avoidance.{key}")
        for key in ("horizon", "upside", "downside")
    }


def _validate_watermark(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise M3ThingModelValidationError(
            "camera_watermark_settings must be a non-empty object"
        )

    keys = set(value)
    unknown = keys - _WATERMARK_KEYS
    if unknown:
        raise M3ThingModelValidationError(
            "camera_watermark_settings contains unsupported fields: "
            f"{sorted(unknown)}"
        )

    result: dict[str, Any] = {}
    for key in _WATERMARK_SWITCH_KEYS:
        if key in value:
            result[key] = _binary_switch(
                value[key],
                name=f"camera_watermark_settings.{key}",
            )

    if "layout" in value:
        layout = _integer(
            value["layout"],
            name="camera_watermark_settings.layout",
        )
        if layout not in (0, 1, 2, 3):
            raise M3ThingModelValidationError(
                "camera_watermark_settings.layout must be between 0 and 3"
            )
        result["layout"] = layout

    if "user_custom_string" in value:
        custom = value["user_custom_string"]
        if not isinstance(custom, str):
            raise M3ThingModelValidationError(
                "camera_watermark_settings.user_custom_string must be text"
            )
        if len(custom.encode("utf-8")) > 250:
            raise M3ThingModelValidationError(
                "camera_watermark_settings.user_custom_string exceeds 250 UTF-8 bytes"
            )
        result["user_custom_string"] = custom

    return result


def validate_m3_property_patch(
    properties: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the four properties DJI documents as rw for M3 Pilot-to-Cloud."""

    if not isinstance(properties, Mapping) or not properties:
        raise M3ThingModelValidationError(
            "at least one M3 property is required"
        )

    unknown = set(properties) - M3_WRITABLE_PROPERTIES
    if unknown:
        raise M3ThingModelValidationError(
            f"unsupported or read-only M3 properties: {sorted(unknown)}"
        )

    result: dict[str, Any] = {}
    for name, value in properties.items():
        if name == "height_limit":
            height = _integer(value, name=name)
            if not 20 <= height <= 1500:
                raise M3ThingModelValidationError(
                    "height_limit must be between 20 and 1500 metres"
                )
            result[name] = height
        elif name == "night_lights_state":
            result[name] = _binary_switch(value, name=name)
        elif name == "obstacle_avoidance":
            result[name] = _validate_obstacle_avoidance(value)
        elif name == "camera_watermark_settings":
            result[name] = _validate_watermark(value)

    return deepcopy(result)
