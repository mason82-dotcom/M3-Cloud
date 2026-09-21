from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

from pymavlink.dialects.v20 import common as mavlink_common

from app.config import Settings
from app.dji.storage_sts import create_pilot_storage_client
from app.dji.wpml import KML_NS, WPML_NS, WPMLCompileError, compile_wpml_kmz


_PLATFORM_KEYS = {
    "M3E": ("0-77-0", ["1-66-0"]),
    "M3T": ("0-77-1", ["1-67-0"]),
    "M3M": ("0-77-2", ["1-68-0"]),
}
_WPML_MODEL_KEYS = {
    (77, 0): ("0-77-0", "M3E"),
    (77, 1): ("0-77-1", "M3T"),
    (77, 2): ("0-77-2", "M3M"),
}
_WPML_PAYLOAD_KEYS = {
    66: "1-66-0",
    67: "1-67-0",
    68: "1-68-0",
}
_TEMPLATE_TYPES = {
    "waypoint": 0,
    "mapping2d": 1,
    "mapping3d": 2,
    "mappingStrip": 3,
}
_MAX_KMZ_BYTES = 128 * 1024 * 1024
_MAX_XML_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class NativeWaylineInspection:
    size_bytes: int
    sha256: str
    drone_model_key: str
    payload_model_keys: list[str]
    template_types: list[int]
    start_wayline_point: dict[str, float] | None


def mission_platform(plan: dict[str, object]) -> str:
    planning = plan.get("planning")
    value = (
        str(planning.get("platform") or "").strip().upper()
        if isinstance(planning, dict)
        else ""
    )
    aliases = {
        "DJI_MAVIC_3E": "M3E",
        "DJI_MAVIC_3T": "M3T",
        "DJI_MAVIC_3M": "M3M",
    }
    value = aliases.get(value, value)
    if value not in _PLATFORM_KEYS:
        raise WPMLCompileError("Mission does not declare M3E, M3T, or M3M platform")
    return value


def model_keys(platform: str) -> tuple[str, list[str]]:
    try:
        drone, payloads = _PLATFORM_KEYS[platform]
    except KeyError as exc:
        raise WPMLCompileError(f"Unsupported DJI wayline platform: {platform}") from exc
    return drone, list(payloads)


def start_wayline_point(plan: dict[str, object]) -> dict[str, float] | None:
    raw = plan.get("items")
    if not isinstance(raw, list):
        return None
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("command") != mavlink_common.MAV_CMD_NAV_WAYPOINT:
            continue
        lat = item.get("latitude_deg")
        lon = item.get("longitude_deg")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return {
                "start_latitude": float(lat),
                # DJI's public schema intentionally spells this "lontitude".
                "start_lontitude": float(lon),
            }
    return None


def compile_mission_wayline(
    plan: dict[str, object],
    *,
    name: str,
):
    platform = mission_platform(plan)
    return compile_wpml_kmz(
        plan,
        platform=platform,
        filename_stem=name,
    )


def wayline_list_item(
    *,
    mission_id: str,
    name: str,
    plan: dict[str, object],
    updated_at_ms: int,
) -> dict[str, Any]:
    platform = mission_platform(plan)
    # Validate that the mission is actually exportable before advertising it to Pilot 2.
    compile_mission_wayline(plan, name=name)
    drone_key, payload_keys = model_keys(platform)
    return {
        "id": mission_id,
        "drone_model_key": drone_key,
        "favorited": False,
        "name": name,
        "payload_model_keys": payload_keys,
        "template_types": [0],
        "action_type": 0,
        "update_time": updated_at_ms,
        "user_name": "M3-Cloud",
        "start_wayline_point": start_wayline_point(plan),
    }


def native_wayline_list_item(
    *,
    wayline_id: str,
    name: str,
    drone_model_key: str,
    payload_model_keys: list[str],
    template_types: list[int],
    favorited: bool,
    updated_at_ms: int,
    start_point: dict[str, float] | None = None,
) -> dict[str, Any]:
    return {
        "id": wayline_id,
        "drone_model_key": drone_model_key,
        "favorited": favorited,
        "name": name,
        "payload_model_keys": list(payload_model_keys),
        "template_types": list(template_types),
        "action_type": 0,
        "update_time": updated_at_ms,
        "user_name": "DJI Pilot 2",
        "start_wayline_point": start_point,
    }


def _required_int(root: ET.Element, path: str, label: str) -> int:
    node = root.find(path, {"wpml": WPML_NS, "kml": KML_NS})
    if node is None or node.text is None:
        raise WPMLCompileError(f"Native DJI KMZ is missing {label}")
    try:
        return int(node.text.strip())
    except ValueError as exc:
        raise WPMLCompileError(f"Native DJI KMZ has invalid {label}") from exc


def _read_required_xml(
    archive: zipfile.ZipFile,
    name: str,
) -> ET.Element:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise WPMLCompileError(f"Native DJI KMZ is missing {name}") from exc
    if info.file_size > _MAX_XML_BYTES:
        raise WPMLCompileError(f"Native DJI KMZ {name} exceeds XML size limit")
    try:
        return ET.fromstring(archive.read(info))
    except (ET.ParseError, RuntimeError, ValueError) as exc:
        raise WPMLCompileError(f"Native DJI KMZ contains invalid XML in {name}") from exc


def _start_point_from_wpml(root: ET.Element) -> dict[str, float] | None:
    node = root.find(
        ".//kml:Placemark/kml:Point/kml:coordinates",
        {"kml": KML_NS, "wpml": WPML_NS},
    )
    if node is None or not node.text:
        return None
    parts = [part.strip() for part in node.text.strip().split(",")]
    if len(parts) < 2:
        return None
    try:
        longitude = float(parts[0])
        latitude = float(parts[1])
    except ValueError:
        return None
    if not (-180.0 <= longitude <= 180.0 and -90.0 <= latitude <= 90.0):
        return None
    return {
        "start_latitude": latitude,
        "start_lontitude": longitude,
    }


def inspect_native_wayline_bytes(payload: bytes) -> NativeWaylineInspection:
    if not payload:
        raise WPMLCompileError("Native DJI KMZ is empty")
    if len(payload) > _MAX_KMZ_BYTES:
        raise WPMLCompileError("Native DJI KMZ exceeds size limit")

    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise WPMLCompileError("Native DJI wayline is not a valid KMZ/ZIP") from exc

    with archive:
        # Refuse suspicious archives before decompressing XML members.
        total_uncompressed = sum(info.file_size for info in archive.infolist())
        if total_uncompressed > _MAX_KMZ_BYTES * 4:
            raise WPMLCompileError("Native DJI KMZ expands beyond safety limit")

        template = _read_required_xml(archive, "wpmz/template.kml")
        waylines = _read_required_xml(archive, "wpmz/waylines.wpml")

    drone_type = _required_int(
        waylines,
        ".//wpml:droneInfo/wpml:droneEnumValue",
        "droneEnumValue",
    )
    drone_subtype = _required_int(
        waylines,
        ".//wpml:droneInfo/wpml:droneSubEnumValue",
        "droneSubEnumValue",
    )
    try:
        drone_model_key, _platform = _WPML_MODEL_KEYS[(drone_type, drone_subtype)]
    except KeyError as exc:
        raise WPMLCompileError(
            f"Native DJI KMZ targets unsupported aircraft {drone_type}/{drone_subtype}"
        ) from exc

    payload_values: set[int] = set()
    for root in (template, waylines):
        for node in root.findall(
            ".//wpml:payloadInfo/wpml:payloadEnumValue",
            {"wpml": WPML_NS, "kml": KML_NS},
        ):
            if node.text:
                try:
                    payload_values.add(int(node.text.strip()))
                except ValueError as exc:
                    raise WPMLCompileError(
                        "Native DJI KMZ has invalid payloadEnumValue"
                    ) from exc

    if not payload_values:
        raise WPMLCompileError("Native DJI KMZ declares no payload")
    try:
        payload_model_keys = sorted(_WPML_PAYLOAD_KEYS[value] for value in payload_values)
    except KeyError as exc:
        raise WPMLCompileError(
            f"Native DJI KMZ targets unsupported payload {exc.args[0]}"
        ) from exc

    template_names = {
        node.text.strip()
        for node in template.findall(
            ".//wpml:templateType",
            {"wpml": WPML_NS, "kml": KML_NS},
        )
        if node.text and node.text.strip()
    }
    if not template_names:
        # Our deterministic M3-Cloud waypoint compiler uses one waypoint folder;
        # native Pilot 2 uploads are required to declare a template type.
        raise WPMLCompileError("Native DJI KMZ declares no templateType")
    try:
        template_types = sorted(_TEMPLATE_TYPES[name] for name in template_names)
    except KeyError as exc:
        raise WPMLCompileError(
            f"Native DJI KMZ uses unsupported template type {exc.args[0]!r}"
        ) from exc

    return NativeWaylineInspection(
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        drone_model_key=drone_model_key,
        payload_model_keys=payload_model_keys,
        template_types=template_types,
        start_wayline_point=_start_point_from_wpml(waylines),
    )


def inspect_native_wayline_object(
    settings: Settings,
    *,
    bucket: str,
    object_key: str,
) -> NativeWaylineInspection:
    client = create_pilot_storage_client(settings)
    head = client.head_object(Bucket=bucket, Key=object_key)
    size = int(head.get("ContentLength") or 0)
    if size <= 0:
        raise WPMLCompileError("Uploaded DJI KMZ object is empty")
    if size > _MAX_KMZ_BYTES:
        raise WPMLCompileError("Uploaded DJI KMZ object exceeds size limit")

    response = client.get_object(Bucket=bucket, Key=object_key)
    body = response["Body"]
    try:
        payload = body.read(_MAX_KMZ_BYTES + 1)
    finally:
        body.close()
    if len(payload) > _MAX_KMZ_BYTES:
        raise WPMLCompileError("Uploaded DJI KMZ object exceeds size limit")
    if len(payload) != size:
        raise WPMLCompileError(
            f"Uploaded DJI KMZ changed while reading: expected {size}, got {len(payload)}"
        )
    return inspect_native_wayline_bytes(payload)


def validate_native_wayline_metadata(
    inspection: NativeWaylineInspection,
    *,
    drone_model_key: str,
    payload_model_keys: list[str],
    template_types: list[int],
) -> None:
    if inspection.drone_model_key != drone_model_key:
        raise WPMLCompileError(
            "DJI wayline aircraft metadata does not match KMZ content: "
            f"{drone_model_key} != {inspection.drone_model_key}"
        )
    if sorted(set(payload_model_keys)) != inspection.payload_model_keys:
        raise WPMLCompileError(
            "DJI wayline payload metadata does not match KMZ content"
        )
    if sorted(set(template_types)) != inspection.template_types:
        raise WPMLCompileError(
            "DJI wayline template metadata does not match KMZ content"
        )
