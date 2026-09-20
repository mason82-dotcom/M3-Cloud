from __future__ import annotations
from copy import deepcopy
from typing import Any

def normalize_aircraft_state(telemetry: dict[str, Any] | None, *, source: str) -> dict[str, Any] | None:
    """Expose common flight facts while retaining source-native mode identifiers."""
    if telemetry is None:
        return None
    result = deepcopy(telemetry)
    native = result.get("flight_state") if isinstance(result.get("flight_state"), dict) else {}
    common: dict[str, Any] = {"source": source}

    if source == "lyrebird":
        common.update({
            "mode": native.get("mode") or result.get("flight_mode"),
            "armed": native.get("armed"),
            "is_flying": native.get("is_flying"),
            "failsafe": native.get("failsafe"),
            "landed_state": native.get("landed_state"),
        })
        common["native"] = {
            "mavlink_custom_mode": native.get("custom_mode"),
            "mavlink_system_status": native.get("system_status"),
            "dji_flight_mode": result.get("flight_mode"),
        }
    elif source == "dji_cloud":
        common.update({"mode": None, "armed": None, "is_flying": None, "failsafe": None, "landed_state": None})
        common["native"] = {
            "dji_mode_code": result.get("mode_code"),
            "dji_mode_code_reason": result.get("mode_code_reason"),
        }
    else:
        common["native"] = {}

    # Do not invent cross-protocol semantics: absent facts remain absent/null.
    result["aircraft_state"] = common
    return result
