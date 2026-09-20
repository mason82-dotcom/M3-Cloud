from __future__ import annotations
from copy import deepcopy
from typing import Any

DJI_CLOUD_MODE_NAMES = {
    0:"STANDBY", 1:"TAKEOFF_PREPARATION", 2:"TAKEOFF_PREPARATION_COMPLETED",
    3:"MANUAL_FLIGHT", 4:"AUTOMATIC_TAKEOFF", 5:"WAYLINE_FLIGHT",
    6:"PANORAMIC_PHOTOGRAPHY", 7:"INTELLIGENT_TRACKING", 8:"ADS_B_AVOIDANCE",
    9:"AUTO_RETURN_TO_HOME", 10:"AUTOMATIC_LANDING", 11:"FORCED_LANDING",
    12:"THREE_BLADE_LANDING", 13:"UPGRADING", 14:"NOT_CONNECTED", 15:"APAS",
    16:"VIRTUAL_STICK", 17:"LIVE_FLIGHT_CONTROLS", 18:"AIRBORNE_RTK_FIXING",
}

def _dji_cloud_state(result: dict[str, Any]) -> dict[str, Any]:
    code = result.get("mode_code")
    mode = DJI_CLOUD_MODE_NAMES.get(code) if isinstance(code, int) and not isinstance(code, bool) else None
    position = result.get("position_state") if isinstance(result.get("position_state"), dict) else {}
    quality = position.get("quality")
    convergence = position.get("convergence")
    rtk_fixed = quality == 10 or convergence == "CONVERGED"
    return {
        "mode": mode,
        "armed": None,
        "is_flying": None,
        "failsafe": None,
        "landed_state": None,
        "home": {
            "latitude": result.get("home_latitude"),
            "longitude": result.get("home_longitude"),
            "distance_m": result.get("home_distance_m"),
        },
        "positioning": {
            "convergence": convergence,
            "quality": quality,
            "gps_satellites": position.get("gps_satellites"),
            "rtk_satellites": position.get("rtk_satellites"),
            "rtk_fixed": rtk_fixed,
        },
        "native": {
            "dji_mode_code": code,
            "dji_mode_code_reason": result.get("mode_code_reason"),
        },
    }

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
        common.update(_dji_cloud_state(result))
    else:
        common["native"] = {}

    # Do not invent cross-protocol semantics: absent facts remain absent/null.
    result["aircraft_state"] = common
    return result
