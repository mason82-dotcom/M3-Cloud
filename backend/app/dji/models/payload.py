from __future__ import annotations

import math
import re
from typing import Any, Iterable


PAYLOAD_TYPE_BY_M3_SUBTYPE = {
    0: 66,  # M3E
    1: 67,  # M3T
}

CAMERA_TYPES_BY_M3_SUBTYPE = {
    0: frozenset({"wide", "zoom"}),
    1: frozenset({"wide", "zoom", "ir"}),
}

_PAYLOAD_INDEX_RE = re.compile(r"^(\d+)-(\d+)-(\d+)$")


class DJIPayloadValidationError(ValueError):
    pass


def finite_number(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DJIPayloadValidationError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise DJIPayloadValidationError(f"{name} must be finite")
    return number


def strict_int(value: Any, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise DJIPayloadValidationError(f"{name} must be an integer")
    return value


def bounded_number(
    value: Any,
    *,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    number = finite_number(value, name=name)
    if not minimum <= number <= maximum:
        raise DJIPayloadValidationError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return number


def validate_payload_index(m3_sub_type: int, payload_index: str) -> str:
    if m3_sub_type not in PAYLOAD_TYPE_BY_M3_SUBTYPE:
        raise DJIPayloadValidationError(
            f"unsupported M3 subtype: {m3_sub_type!r}"
        )
    if not isinstance(payload_index, str):
        raise DJIPayloadValidationError("payload_index must be text")

    match = _PAYLOAD_INDEX_RE.fullmatch(payload_index.strip())
    if match is None:
        raise DJIPayloadValidationError(
            "payload_index must use DJI type-subtype-gimbalindex format"
        )
    payload_type = int(match.group(1))
    expected = PAYLOAD_TYPE_BY_M3_SUBTYPE[m3_sub_type]
    if payload_type != expected:
        raise DJIPayloadValidationError(
            f"payload_index {payload_index!r} does not belong to M3 subtype "
            f"{m3_sub_type}; expected payload type {expected}"
        )
    return payload_index.strip()


def validate_camera_type(m3_sub_type: int, camera_type: str) -> str:
    allowed = CAMERA_TYPES_BY_M3_SUBTYPE.get(m3_sub_type)
    if allowed is None:
        raise DJIPayloadValidationError(
            f"unsupported M3 subtype: {m3_sub_type!r}"
        )
    if camera_type not in allowed:
        raise DJIPayloadValidationError(
            f"camera type {camera_type!r} is not allowed for M3 subtype "
            f"{m3_sub_type}; allowed={sorted(allowed)}"
        )
    return camera_type


def require_m3t(m3_sub_type: int, operation: str) -> None:
    if m3_sub_type != 1:
        raise DJIPayloadValidationError(
            f"{operation} is only valid for the M3T infrared payload"
        )


def normalized_storage_settings(
    m3_sub_type: int,
    values: Iterable[str],
) -> list[str]:
    allowed = {"current", "vision"}
    if m3_sub_type == 1:
        allowed.add("ir")
    elif m3_sub_type != 0:
        raise DJIPayloadValidationError(
            f"unsupported M3 subtype: {m3_sub_type!r}"
        )

    normalized: list[str] = []
    for value in values:
        if value not in allowed:
            raise DJIPayloadValidationError(
                f"unsupported storage target {value!r}; allowed={sorted(allowed)}"
            )
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        raise DJIPayloadValidationError(
            "at least one storage target is required"
        )
    return normalized


def validate_unit_point(x: Any, y: Any) -> tuple[float, float]:
    return (
        bounded_number(x, name="x", minimum=0.0, maximum=1.0),
        bounded_number(y, name="y", minimum=0.0, maximum=1.0),
    )


def validate_unit_rect(
    x: Any,
    y: Any,
    width: Any,
    height: Any,
) -> tuple[float, float, float, float]:
    left, top = validate_unit_point(x, y)
    w = bounded_number(width, name="width", minimum=0.0, maximum=1.0)
    h = bounded_number(height, name="height", minimum=0.0, maximum=1.0)
    if left + w > 1.0 or top + h > 1.0:
        raise DJIPayloadValidationError(
            "normalized rectangle must remain inside the camera frame"
        )
    return left, top, w, h
