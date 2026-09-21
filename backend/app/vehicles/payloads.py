from __future__ import annotations
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

class AircraftPlatform(StrEnum):
    M3E = "M3E"
    M3T = "M3T"
    M3M = "M3M"
    M4T = "M4T"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class PayloadCapabilities:
    platform: AircraftPlatform
    rgb: bool
    wide: bool
    zoom: bool
    thermal: bool
    multispectral: bool
    lrf: bool
    capture_profiles: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["platform"] = self.platform.value
        value["capture_profiles"] = list(self.capture_profiles)
        return value

_CAPABILITIES = {
    AircraftPlatform.M3E: PayloadCapabilities(AircraftPlatform.M3E, True, True, True, False, False, False, ("M3E_MAPPING",)),
    AircraftPlatform.M3T: PayloadCapabilities(AircraftPlatform.M3T, True, True, True, True, False, True, ("M3T_WIDE", "M3T_THERMAL")),
    AircraftPlatform.M3M: PayloadCapabilities(AircraftPlatform.M3M, True, False, False, False, True, False, ("M3M_RGB", "M3M_RGB_MULTISPECTRAL")),
    AircraftPlatform.M4T: PayloadCapabilities(AircraftPlatform.M4T, True, True, True, True, False, True, ("M4T_WIDE", "M4T_THERMAL")),
    AircraftPlatform.UNKNOWN: PayloadCapabilities(AircraftPlatform.UNKNOWN, False, False, False, False, False, False, ()),
}

def capabilities_for(platform: AircraftPlatform) -> PayloadCapabilities:
    return _CAPABILITIES[platform]

def platform_from_camera_type(camera_type: str | None) -> AircraftPlatform:
    """Mirror Lyrebird CameraPlatformCapabilities; unknown/new SDK types fail closed."""
    name = (camera_type or "").strip().upper()
    if name == "M3E":
        return AircraftPlatform.M3E
    if name in {"M3T", "M3TA"}:
        return AircraftPlatform.M3T
    if name == "M3M":
        return AircraftPlatform.M3M
    if name == "M4T":
        return AircraftPlatform.M4T
    return AircraftPlatform.UNKNOWN

def platform_from_explicit_model(model: str | None) -> AircraftPlatform:
    """Accept explicit product identity only; never infer a model from thermal capability."""
    name = (model or "").strip().upper().replace("DJI ", "")
    aliases = {
        "M3E": AircraftPlatform.M3E, "MAVIC 3 ENTERPRISE": AircraftPlatform.M3E,
        "M3T": AircraftPlatform.M3T, "M3TA": AircraftPlatform.M3T, "MAVIC 3 THERMAL": AircraftPlatform.M3T,
        "M3M": AircraftPlatform.M3M, "MAVIC 3 MULTISPECTRAL": AircraftPlatform.M3M,
        "M4T": AircraftPlatform.M4T, "MATRICE 4T": AircraftPlatform.M4T,
    }
    return aliases.get(name, AircraftPlatform.UNKNOWN)

def attach_payload_capabilities(telemetry: dict[str, Any] | None, platform: AircraftPlatform) -> dict[str, Any] | None:
    if telemetry is None and platform == AircraftPlatform.UNKNOWN:
        return None
    result = dict(telemetry or {})
    result["payload"] = capabilities_for(platform).as_dict()
    return result
