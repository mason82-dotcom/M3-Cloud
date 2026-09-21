from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

from pymavlink.dialects.v20 import common as mavlink_common


KML_NS = "http://www.opengis.net/kml/2.2"
WPML_NS = "http://www.dji.com/wpmz/1.0.2"
ET.register_namespace("", KML_NS)
ET.register_namespace("wpml", WPML_NS)

_DRONE = {
    "M3E": (77, 0, 66),
    "DJI_MAVIC_3E": (77, 0, 66),
    "M3T": (77, 1, 67),
    "DJI_MAVIC_3T": (77, 1, 67),
    "M3M": (77, 2, 68),
    "DJI_MAVIC_3M": (77, 2, 68),
}

_ALLOWED_COMMANDS = {
    mavlink_common.MAV_CMD_NAV_WAYPOINT,
    mavlink_common.MAV_CMD_NAV_TAKEOFF,
    mavlink_common.MAV_CMD_NAV_LAND,
    mavlink_common.MAV_CMD_NAV_RETURN_TO_LAUNCH,
    mavlink_common.MAV_CMD_DO_CHANGE_SPEED,
    mavlink_common.MAV_CMD_DO_GIMBAL_MANAGER_PITCHYAW,
    mavlink_common.MAV_CMD_DO_MOUNT_CONTROL,
    mavlink_common.MAV_CMD_DO_SET_CAM_TRIGG_DIST,
}


class WPMLCompileError(ValueError):
    pass


@dataclass(frozen=True)
class WPMLArtifact:
    filename: str
    kmz: bytes
    waypoint_count: int
    finish_action: str
    platform: str
    auto_flight_speed_mps: float
    gimbal_pitch_deg: float | None
    distance_trigger_groups: int


def _kml(name: str) -> str:
    return f"{{{KML_NS}}}{name}"


def _wpml(name: str) -> str:
    return f"{{{WPML_NS}}}{name}"


def _child(parent: ET.Element, name: str, value: object | None = None) -> ET.Element:
    element = ET.SubElement(parent, _wpml(name))
    if value is not None:
        element.text = str(value)
    return element


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WPMLCompileError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise WPMLCompileError(f"{label} must be finite")
    return number


def _platform(plan: dict[str, object], explicit: str | None) -> str:
    if explicit:
        candidate = explicit.strip().upper()
    else:
        planning = plan.get("planning")
        candidate = (
            str(planning.get("platform") or "").strip().upper()
            if isinstance(planning, dict)
            else ""
        )
    aliases = {
        "DJI_MAVIC_3E": "M3E",
        "DJI_MAVIC_3T": "M3T",
        "DJI_MAVIC_3M": "M3M",
    }
    candidate = aliases.get(candidate, candidate)
    if candidate not in {"M3E", "M3T", "M3M"}:
        raise WPMLCompileError("DJI WPML requires an explicit M3E, M3T, or M3M platform")
    return candidate


def _items(plan: dict[str, object]) -> list[dict[str, object]]:
    raw = plan.get("items")
    if not isinstance(raw, list) or not raw:
        raise WPMLCompileError("Mission plan has no items")
    items = [item for item in raw if isinstance(item, dict)]
    if len(items) != len(raw):
        raise WPMLCompileError("Mission plan contains a non-object item")
    for expected, item in enumerate(items):
        if item.get("seq") != expected:
            raise WPMLCompileError("Mission item sequence must be contiguous")
        command = item.get("command")
        if command not in _ALLOWED_COMMANDS:
            raise WPMLCompileError(
                f"Mission command {command!r} is not safely mapped to DJI WPML"
            )
    return items


def _finish_action(items: list[dict[str, object]]) -> str:
    commands = [item.get("command") for item in items]
    if mavlink_common.MAV_CMD_NAV_RETURN_TO_LAUNCH in commands:
        return "goHome"
    if mavlink_common.MAV_CMD_NAV_LAND in commands:
        return "autoLand"
    return "noAction"


def _speed(items: list[dict[str, object]], plan: dict[str, object]) -> float:
    for item in items:
        if item.get("command") == mavlink_common.MAV_CMD_DO_CHANGE_SPEED:
            value = item.get("param2")
            if value is not None:
                return max(0.1, min(15.0, _finite(value, "mission speed")))

    planning = plan.get("planning")
    if isinstance(planning, dict):
        derived = planning.get("derived")
        if isinstance(derived, dict) and derived.get("effective_speed_mps") is not None:
            return max(
                0.1,
                min(15.0, _finite(derived["effective_speed_mps"], "effective speed")),
            )
    return 5.0


def _gimbal_pitch(items: list[dict[str, object]]) -> float | None:
    for item in items:
        if item.get("command") in {
            mavlink_common.MAV_CMD_DO_GIMBAL_MANAGER_PITCHYAW,
            mavlink_common.MAV_CMD_DO_MOUNT_CONTROL,
        }:
            value = item.get("param1")
            if value is not None:
                return _finite(value, "gimbal pitch")
    return None


def _waypoints(items: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        item
        for item in items
        if item.get("command") == mavlink_common.MAV_CMD_NAV_WAYPOINT
    ]


def _trigger_groups(
    items: list[dict[str, object]],
    waypoints: list[dict[str, object]],
) -> list[tuple[int, int, float]]:
    seq_to_waypoint_index = {
        int(item["seq"]): index for index, item in enumerate(waypoints)
    }
    groups: list[tuple[int, int, float]] = []
    active: tuple[int, float] | None = None
    last_waypoint_index: int | None = None

    for item in items:
        seq = int(item["seq"])
        command = item.get("command")
        if command == mavlink_common.MAV_CMD_NAV_WAYPOINT:
            last_waypoint_index = seq_to_waypoint_index[seq]
            continue
        if command != mavlink_common.MAV_CMD_DO_SET_CAM_TRIGG_DIST:
            continue

        distance = _finite(item.get("param1", 0.0), "camera trigger distance")
        if distance > 0:
            if last_waypoint_index is None:
                raise WPMLCompileError("Distance trigger starts before the first waypoint")
            if active is not None:
                raise WPMLCompileError("Nested camera distance triggers are unsupported")
            active = (last_waypoint_index, distance)
        elif active is not None:
            if last_waypoint_index is None or last_waypoint_index <= active[0]:
                raise WPMLCompileError("Distance trigger has no waypoint span")
            groups.append((active[0], last_waypoint_index, active[1]))
            active = None

    if active is not None:
        raise WPMLCompileError("Camera distance trigger is not explicitly stopped")
    return groups


def _mission_config(
    document: ET.Element,
    *,
    platform: str,
    finish_action: str,
    rth_height: float,
) -> None:
    drone_type, drone_subtype, payload_type = _DRONE[platform]
    config = _child(document, "missionConfig")
    _child(config, "flyToWaylineMode", "safely")
    _child(config, "finishAction", finish_action)
    _child(config, "exitOnRCLost", "executeLostAction")
    _child(config, "executeRCLostAction", "goBack")
    _child(config, "takeOffSecurityHeight", max(1.2, min(1500.0, rth_height)))
    _child(config, "globalTransitionalSpeed", 10)
    _child(config, "globalRTHHeight", max(2.0, min(1500.0, rth_height)))

    drone = _child(config, "droneInfo")
    _child(drone, "droneEnumValue", drone_type)
    _child(drone, "droneSubEnumValue", drone_subtype)

    payload = _child(config, "payloadInfo")
    _child(payload, "payloadEnumValue", payload_type)
    _child(payload, "payloadPositionIndex", 0)


def _start_gimbal_action(folder: ET.Element, pitch: float | None) -> None:
    if pitch is None:
        return
    group = _child(folder, "startActionGroup")
    _child(group, "actionGroupId", 60000)
    _child(group, "actionGroupStartIndex", 0)
    _child(group, "actionGroupEndIndex", 0)
    _child(group, "actionGroupMode", "sequence")
    trigger = _child(group, "actionTrigger")
    _child(trigger, "actionTriggerType", "reachPoint")
    action = _child(group, "action")
    _child(action, "actionId", 0)
    _child(action, "actionActuatorFunc", "gimbalRotate")
    params = _child(action, "actionActuatorFuncParam")
    _child(params, "gimbalHeadingYawBase", "north")
    _child(params, "gimbalRotateMode", "absoluteAngle")
    _child(params, "gimbalPitchRotateEnable", 1)
    _child(params, "gimbalPitchRotateAngle", pitch)
    _child(params, "gimbalRollRotateEnable", 0)
    _child(params, "gimbalRollRotateAngle", 0)
    _child(params, "gimbalYawRotateEnable", 0)
    _child(params, "gimbalYawRotateAngle", 0)
    _child(params, "gimbalRotateTimeEnable", 0)
    _child(params, "gimbalRotateTime", 0)
    _child(params, "payloadPositionIndex", 0)


def _capture_action_group(
    placemark: ET.Element,
    *,
    group_id: int,
    start_index: int,
    end_index: int,
    distance_m: float,
) -> None:
    group = _child(placemark, "actionGroup")
    _child(group, "actionGroupId", group_id)
    _child(group, "actionGroupStartIndex", start_index)
    _child(group, "actionGroupEndIndex", end_index)
    _child(group, "actionGroupMode", "sequence")
    trigger = _child(group, "actionTrigger")
    _child(trigger, "actionTriggerType", "multipleDistance")
    _child(trigger, "actionTriggerParam", distance_m)
    action = _child(group, "action")
    _child(action, "actionId", 0)
    _child(action, "actionActuatorFunc", "takePhoto")
    params = _child(action, "actionActuatorFuncParam")
    _child(params, "fileSuffix", f"M3CLOUD_G{group_id}")
    _child(params, "payloadPositionIndex", 0)
    _child(params, "useGlobalPayloadLensIndex", 1)


def _waylines_xml(
    plan: dict[str, object],
    *,
    platform: str,
    speed: float,
    finish_action: str,
    pitch: float | None,
    waypoints: list[dict[str, object]],
    trigger_groups: list[tuple[int, int, float]],
) -> bytes:
    root = ET.Element(_kml("kml"))
    document = ET.SubElement(root, _kml("Document"))
    max_altitude = max(_finite(item["altitude_m"], "waypoint altitude") for item in waypoints)
    _mission_config(
        document,
        platform=platform,
        finish_action=finish_action,
        rth_height=max(20.0, max_altitude),
    )

    folder = ET.SubElement(document, _kml("Folder"))
    _child(folder, "templateId", 0)
    _child(folder, "executeHeightMode", "relativeToStartPoint")
    _child(folder, "waylineId", 0)
    _child(folder, "autoFlightSpeed", speed)
    _start_gimbal_action(folder, pitch)

    groups_by_start: dict[int, list[tuple[int, int, float]]] = {}
    for group in trigger_groups:
        groups_by_start.setdefault(group[0], []).append(group)

    for index, item in enumerate(waypoints):
        placemark = ET.SubElement(folder, _kml("Placemark"))
        point = ET.SubElement(placemark, _kml("Point"))
        coordinates = ET.SubElement(point, _kml("coordinates"))
        lon = _finite(item["longitude_deg"], "longitude")
        lat = _finite(item["latitude_deg"], "latitude")
        coordinates.text = f"{lon:.9f},{lat:.9f}"
        _child(placemark, "index", index)
        _child(placemark, "executeHeight", _finite(item["altitude_m"], "altitude"))
        _child(placemark, "waypointSpeed", speed)

        heading = _child(placemark, "waypointHeadingParam")
        _child(heading, "waypointHeadingMode", "followWayline")

        turn = _child(placemark, "waypointTurnParam")
        _child(turn, "waypointTurnMode", "toPointAndStopWithDiscontinuityCurvature")
        _child(turn, "waypointTurnDampingDist", 0)

        for group_id, (start, end, distance) in enumerate(
            groups_by_start.get(index, []),
            start=1000 + index * 10,
        ):
            _capture_action_group(
                placemark,
                group_id=group_id,
                start_index=start,
                end_index=end,
                distance_m=distance,
            )

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _template_xml(
    *,
    platform: str,
    speed: float,
    finish_action: str,
    waypoints: list[dict[str, object]],
) -> bytes:
    root = ET.Element(_kml("kml"))
    document = ET.SubElement(root, _kml("Document"))
    _child(document, "author", "M3-Cloud")
    _child(document, "createTime", 0)
    _child(document, "updateTime", 0)

    max_altitude = max(_finite(item["altitude_m"], "waypoint altitude") for item in waypoints)
    _mission_config(
        document,
        platform=platform,
        finish_action=finish_action,
        rth_height=max(20.0, max_altitude),
    )

    folder = ET.SubElement(document, _kml("Folder"))
    _child(folder, "templateType", "waypoint")
    _child(folder, "templateId", 0)
    coordinate = _child(folder, "waylineCoordinateSysParam")
    _child(coordinate, "coordinateMode", "WGS84")
    _child(coordinate, "heightMode", "relativeToStartPoint")
    _child(coordinate, "positioningType", "GPS")
    _child(folder, "autoFlightSpeed", speed)
    _child(folder, "globalWaypointTurnMode", "toPointAndStopWithDiscontinuityCurvature")
    _child(folder, "globalUseStraightLine", 1)

    for index, item in enumerate(waypoints):
        placemark = ET.SubElement(folder, _kml("Placemark"))
        point = ET.SubElement(placemark, _kml("Point"))
        coordinates = ET.SubElement(point, _kml("coordinates"))
        coordinates.text = (
            f"{_finite(item['longitude_deg'], 'longitude'):.9f},"
            f"{_finite(item['latitude_deg'], 'latitude'):.9f}"
        )
        _child(placemark, "index", index)
        _child(placemark, "height", _finite(item["altitude_m"], "altitude"))
        _child(placemark, "useGlobalHeight", 0)
        _child(placemark, "useGlobalSpeed", 1)
        _child(placemark, "useGlobalHeadingParam", 1)
        _child(placemark, "useGlobalTurnParam", 1)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def compile_wpml_kmz(
    plan: dict[str, object],
    *,
    platform: str | None = None,
    filename_stem: str = "m3cloud-wayline",
) -> WPMLArtifact:
    items = _items(plan)
    selected_platform = _platform(plan, platform)
    waypoints = _waypoints(items)
    if not waypoints:
        raise WPMLCompileError("DJI WPML mission requires at least one NAV_WAYPOINT")

    speed = _speed(items, plan)
    finish_action = _finish_action(items)
    pitch = _gimbal_pitch(items)
    trigger_groups = _trigger_groups(items, waypoints)

    waylines = _waylines_xml(
        plan,
        platform=selected_platform,
        speed=speed,
        finish_action=finish_action,
        pitch=pitch,
        waypoints=waypoints,
        trigger_groups=trigger_groups,
    )
    template = _template_xml(
        platform=selected_platform,
        speed=speed,
        finish_action=finish_action,
        waypoints=waypoints,
    )

    output = io.BytesIO()
    # Fixed DOS timestamp and sorted member order keep identical plans byte-identical.
    fixed_time = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, payload in (
            ("wpmz/template.kml", template),
            ("wpmz/waylines.wpml", waylines),
        ):
            info = zipfile.ZipInfo(path, date_time=fixed_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, payload)

    safe_stem = "".join(
        character if character.isalnum() or character in "-_." else "_"
        for character in filename_stem
    ).strip("._") or "m3cloud-wayline"

    return WPMLArtifact(
        filename=f"{safe_stem}.kmz",
        kmz=output.getvalue(),
        waypoint_count=len(waypoints),
        finish_action=finish_action,
        platform=selected_platform,
        auto_flight_speed_mps=speed,
        gimbal_pitch_deg=pitch,
        distance_trigger_groups=len(trigger_groups),
    )
