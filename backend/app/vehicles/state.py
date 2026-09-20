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
    # Pilot-to-Cloud M3 position_state exposes convergence, acquisition quality and
    # satellite counts. It does not expose the MSDK RTK positioning solution (FLOAT/FIXED).
    # Keep fix state unknown even if an unexpected quality value is received; source-native
    # values remain available under positioning.native for diagnostics.
    rtk = {
        "enabled": None,
        "connected": None,
        "healthy": None,
        "fix": "UNKNOWN",
        "raw_fix": None,
        "age_ms": None,
        "source": None,
        "std_latitude_m": None,
        "std_longitude_m": None,
        "std_altitude_m": None,
        "satellites": position.get("rtk_satellites"),
        "convergence": convergence,
        "quality": quality,
    }
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
            "rtk_fixed": None,
            "fix": "UNKNOWN",
            "position_source": "DJI_CLOUD",
            "rtk": rtk,
            "native": {
                "dji_quality": quality,
                "dji_convergence": convergence,
                "dji_is_fixed_code": position.get("code"),
            },
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
        positioning = deepcopy(result.get("positioning")) if isinstance(result.get("positioning"), dict) else {}
        rtk = result.get("rtk") if isinstance(result.get("rtk"), dict) else {}
        # Fold the private RTK diagnostic surface into the canonical positioning object.
        # Keep the nested rtk object in result for transport-level diagnostics/backwards compatibility.
        if rtk:
            positioning["rtk"] = {
                "enabled": rtk.get("enabled"),
                "connected": rtk.get("connected"),
                "healthy": rtk.get("healthy"),
                "fix": rtk.get("fix"),
                "raw_fix": rtk.get("raw_fix"),
                "age_ms": rtk.get("age_ms"),
                "source": rtk.get("source"),
                "std_latitude_m": rtk.get("std_latitude_m"),
                "std_longitude_m": rtk.get("std_longitude_m"),
                "std_altitude_m": rtk.get("std_altitude_m"),
            }
            native_positioning = positioning.get("native") if isinstance(positioning.get("native"), dict) else {}
            native_positioning = deepcopy(native_positioning)
            if rtk.get("raw_fix") is not None:
                native_positioning["dji_rtk_raw_fix"] = rtk.get("raw_fix")
            if rtk.get("source") is not None:
                native_positioning["dji_rtk_source"] = rtk.get("source")
            if native_positioning:
                positioning["native"] = native_positioning

        # The private RTK diagnostic message is authoritative for freshness. In particular,
        # STALE must override an older GPS_RAW_INT FIXED/FLOAT value retained by deep merge.
        if rtk.get("fix") == "STALE":
            positioning["fix"] = "STALE"
            positioning["rtk_stale"] = True
            positioning["position_source"] = "FLIGHT_CONTROLLER"
        elif rtk.get("fix") in ("FIXED", "FLOAT"):
            positioning["fix"] = rtk["fix"]
            positioning["rtk_stale"] = False
            positioning["position_source"] = "RTK_FUSED"
        common.update({
            "mode": native.get("mode") or result.get("flight_mode"),
            "armed": native.get("armed"),
            "is_flying": native.get("is_flying"),
            "failsafe": native.get("failsafe"),
            "landed_state": native.get("landed_state"),
            "positioning": positioning,
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
