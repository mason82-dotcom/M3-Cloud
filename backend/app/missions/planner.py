from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable

from pymavlink.dialects.v20 import common as mavlink_common

from app.missions.plans import MAX_MISSION_ITEMS, compatibility, normalize_plan


EARTH_RADIUS_M = 6_378_137.0
MAX_LOCAL_PLANNER_SPAN_M = 20_000.0
MIN_SEGMENT_M = 0.5


@dataclass(frozen=True)
class CameraPlanningProfile:
    key: str
    platform: str
    capture_profile: str
    planning_sensor: str
    width_px: int
    height_px: int
    horizontal_fov_deg: float
    vertical_fov_deg: float
    min_interval_s: float
    geometry_source: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _axes_from_diagonal_fov(
    diagonal_fov_deg: float,
    width_px: int,
    height_px: int,
) -> tuple[float, float]:
    """Resolve horizontal/vertical FOV from a diagonal FOV and image aspect ratio."""
    diagonal_tan = math.tan(math.radians(diagonal_fov_deg) / 2.0)
    aspect = width_px / height_px
    vertical_tan = diagonal_tan / math.sqrt(aspect * aspect + 1.0)
    horizontal_tan = aspect * vertical_tan
    return (
        math.degrees(2.0 * math.atan(horizontal_tan)),
        math.degrees(2.0 * math.atan(vertical_tan)),
    )


_M3E_HFOV, _M3E_VFOV = _axes_from_diagonal_fov(84.0, 5280, 3956)
_M3T_12MP_HFOV, _M3T_12MP_VFOV = _axes_from_diagonal_fov(84.0, 4000, 3000)


# These are deliberately the profiles Lyrebird's current DJI-native survey path can prepare
# automatically. M3T_THERMAL and M3M_RGB are valid capture profiles, but are not exposed here
# until a mission can carry an explicit capture-profile selection end-to-end.
PLANNING_PROFILES: dict[str, CameraPlanningProfile] = {
    "M3E_MAPPING": CameraPlanningProfile(
        key="M3E_MAPPING",
        platform="M3E",
        capture_profile="M3E_MAPPING",
        planning_sensor="RGB_WIDE_20MP",
        width_px=5280,
        height_px=3956,
        horizontal_fov_deg=_M3E_HFOV,
        vertical_fov_deg=_M3E_VFOV,
        min_interval_s=0.7,
        geometry_source="DJI_SPEC_DIAGONAL_FOV_DERIVED_AXES",
        note=(
            "84 degree diagonal FOV and 5280x3956 image size are DJI specifications; "
            "horizontal/vertical FOV are derived from the image aspect ratio."
        ),
    ),
    "M3T_WIDE": CameraPlanningProfile(
        key="M3T_WIDE",
        platform="M3T",
        capture_profile="M3T_WIDE",
        planning_sensor="RGB_WIDE_12MP",
        width_px=4000,
        height_px=3000,
        horizontal_fov_deg=_M3T_12MP_HFOV,
        vertical_fov_deg=_M3T_12MP_VFOV,
        min_interval_s=2.0,
        geometry_source="DJI_SPEC_12MP_MODE_DERIVED_DIMENSIONS",
        note=(
            "DJI specifies an 84 degree wide-camera FOV and 12 MP/48 MP modes. "
            "The planner models the 12 MP 4:3 mode as 4000x3000; verify the actual "
            "PHOTO_NORMAL media dimensions on the target firmware before field use."
        ),
    ),
    "M3M_RGB_MULTISPECTRAL": CameraPlanningProfile(
        key="M3M_RGB_MULTISPECTRAL",
        platform="M3M",
        capture_profile="M3M_RGB_MULTISPECTRAL",
        planning_sensor="MULTISPECTRAL_5MP_LIMITING_FOOTPRINT",
        width_px=2592,
        height_px=1944,
        horizontal_fov_deg=61.2,
        vertical_fov_deg=48.10,
        min_interval_s=2.0,
        geometry_source="DJI_SPEC",
        note=(
            "The multispectral sensor is the limiting footprint/cadence for the current "
            "RGB+NDVI+G+R+RE+NIR Lyrebird survey profile."
        ),
    ),
}

DEFAULT_PROFILE_BY_PLATFORM = {
    "M3E": "M3E_MAPPING",
    "M3T": "M3T_WIDE",
    "M3M": "M3M_RGB_MULTISPECTRAL",
}


def planner_profile_catalog() -> list[dict[str, Any]]:
    return [profile.as_dict() for profile in PLANNING_PROFILES.values()]


def default_profile_for(platform: str) -> CameraPlanningProfile:
    key = DEFAULT_PROFILE_BY_PLATFORM.get(platform.upper())
    if key is None:
        raise ValueError(f"Unsupported planner platform: {platform}")
    return PLANNING_PROFILES[key]


def planning_profile(platform: str, capture_profile: str | None) -> CameraPlanningProfile:
    platform_name = platform.strip().upper()
    profile = (
        default_profile_for(platform_name)
        if not capture_profile
        else PLANNING_PROFILES.get(capture_profile.strip().upper())
    )
    if profile is None:
        raise ValueError(f"Unsupported capture profile: {capture_profile}")
    if profile.platform != platform_name:
        raise ValueError(
            f"Capture profile {profile.key} belongs to {profile.platform}, not {platform_name}"
        )
    return profile


def _finite(value: float, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _normalise_polygon(
    points: Iterable[tuple[float, float]],
) -> list[tuple[float, float]]:
    result = [(_finite(lat, "latitude"), _finite(lon, "longitude")) for lat, lon in points]
    if len(result) >= 2 and result[0] == result[-1]:
        result.pop()
    if len(result) < 3:
        raise ValueError("Survey polygon requires at least three distinct vertices")
    if len(result) > 200:
        raise ValueError("Survey polygon exceeds 200 vertices")
    for lat, lon in result:
        if not -90.0 <= lat <= 90.0:
            raise ValueError("Survey polygon latitude out of range")
        if not -180.0 <= lon <= 180.0:
            raise ValueError("Survey polygon longitude out of range")
    for current, following in zip(result, result[1:] + result[:1]):
        if current == following:
            raise ValueError("Survey polygon contains duplicate consecutive vertices")
    return result


def _local_projection(
    points: list[tuple[float, float]],
) -> tuple[list[tuple[float, float]], Any]:
    lat0 = sum(lat for lat, _ in points) / len(points)
    lon0 = sum(lon for _, lon in points) / len(points)
    cos_lat0 = math.cos(math.radians(lat0))
    if abs(cos_lat0) < 1e-8:
        raise ValueError("Survey polygon is too close to a geographic pole")

    projected: list[tuple[float, float]] = []
    for lat, lon in points:
        x = EARTH_RADIUS_M * cos_lat0 * math.radians(lon - lon0)
        y = EARTH_RADIUS_M * math.radians(lat - lat0)
        projected.append((x, y))

    def inverse(x: float, y: float) -> tuple[float, float]:
        return (
            lat0 + math.degrees(y / EARTH_RADIUS_M),
            lon0 + math.degrees(x / (EARTH_RADIUS_M * cos_lat0)),
        )

    return projected, inverse


def _cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    ab_c = _cross(a, b, c)
    ab_d = _cross(a, b, d)
    cd_a = _cross(c, d, a)
    cd_b = _cross(c, d, b)
    eps = 1e-8

    if abs(ab_c) < eps and abs(ab_d) < eps and abs(cd_a) < eps and abs(cd_b) < eps:
        def overlaps(a1: float, a2: float, b1: float, b2: float) -> bool:
            return max(min(a1, a2), min(b1, b2)) <= min(max(a1, a2), max(b1, b2)) + eps

        return overlaps(a[0], b[0], c[0], d[0]) and overlaps(a[1], b[1], c[1], d[1])

    return (
        (ab_c > eps and ab_d < -eps or ab_c < -eps and ab_d > eps)
        and (cd_a > eps and cd_b < -eps or cd_a < -eps and cd_b > eps)
    )


def _validate_simple_polygon(points: list[tuple[float, float]]) -> None:
    count = len(points)
    closed = points + [points[0]]
    for i in range(count):
        a, b = closed[i], closed[i + 1]
        for j in range(i + 1, count):
            # Adjacent edges share one endpoint by construction; first/last are adjacent too.
            if j == i or j == i + 1 or (i == 0 and j == count - 1):
                continue
            c, d = closed[j], closed[j + 1]
            if _segments_intersect(a, b, c, d):
                raise ValueError("Survey polygon self-intersects")


def _polygon_area(points: list[tuple[float, float]]) -> float:
    closed = points + [points[0]]
    return abs(
        sum(
            a[0] * b[1] - b[0] * a[1]
            for a, b in zip(closed, closed[1:])
        )
    ) / 2.0


def _scan_segments(
    polygon_xy: list[tuple[float, float]],
    *,
    heading_deg: float,
    line_spacing_m: float,
    footprint_cross_m: float,
    overshoot_m: float,
) -> tuple[list[tuple[tuple[float, float], tuple[float, float]]], int, float]:
    theta = math.radians(heading_deg)

    def to_uv(point: tuple[float, float]) -> tuple[float, float]:
        x, y = point
        # u follows the flight heading; v is the cross-track axis.
        return (
            x * math.sin(theta) + y * math.cos(theta),
            x * math.cos(theta) - y * math.sin(theta),
        )

    def to_xy(u: float, v: float) -> tuple[float, float]:
        return (
            u * math.sin(theta) + v * math.cos(theta),
            u * math.cos(theta) - v * math.sin(theta),
        )

    polygon_uv = [to_uv(point) for point in polygon_xy]
    cross_values = [v for _, v in polygon_uv]
    minimum = min(cross_values)
    maximum = max(cross_values)
    span = maximum - minimum

    if span <= footprint_cross_m:
        levels = [(minimum + maximum) / 2.0]
        actual_spacing = span
    else:
        usable = span - footprint_cross_m
        interval_count = max(1, math.ceil(usable / line_spacing_m))
        actual_spacing = usable / interval_count
        levels = [
            minimum + footprint_cross_m / 2.0 + index * actual_spacing
            for index in range(interval_count + 1)
        ]

    closed = polygon_uv + [polygon_uv[0]]
    result: list[tuple[tuple[float, float], tuple[float, float]]] = []

    for line_index, level in enumerate(levels):
        intersections: list[float] = []
        for (u1, v1), (u2, v2) in zip(closed, closed[1:]):
            # Half-open crossing rule avoids counting a vertex twice.
            if (v1 <= level < v2) or (v2 <= level < v1):
                ratio = (level - v1) / (v2 - v1)
                intersections.append(u1 + ratio * (u2 - u1))
        intersections.sort()

        pairs: list[tuple[float, float]] = []
        for index in range(0, len(intersections) - 1, 2):
            start_u = intersections[index]
            end_u = intersections[index + 1]
            if end_u - start_u >= MIN_SEGMENT_M:
                pairs.append((start_u - overshoot_m, end_u + overshoot_m))

        # Boustrophedon ordering keeps the dead-head distance between adjacent lines short.
        if line_index % 2:
            pairs = [(end_u, start_u) for start_u, end_u in reversed(pairs)]

        for start_u, end_u in pairs:
            result.append((to_xy(start_u, level), to_xy(end_u, level)))

    if not result:
        raise ValueError("Survey polygon produced no flyable scan segments")
    return result, len(levels), actual_spacing


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def build_grid_preview(
    *,
    platform: str,
    capture_profile: str | None,
    polygon: Iterable[tuple[float, float]],
    gsd_cm: float,
    forward_overlap_pct: float,
    side_overlap_pct: float,
    direction_deg: float,
    speed_mps: float,
    gimbal_pitch_deg: float = -90.0,
    overshoot_m: float | None = None,
) -> dict[str, Any]:
    profile = planning_profile(platform, capture_profile)
    vertices = _normalise_polygon(polygon)
    polygon_xy, inverse = _local_projection(vertices)
    _validate_simple_polygon(polygon_xy)

    area_m2 = _polygon_area(polygon_xy)
    if area_m2 < 1.0:
        raise ValueError("Survey polygon area is too small")

    x_values = [point[0] for point in polygon_xy]
    y_values = [point[1] for point in polygon_xy]
    span_m = max(max(x_values) - min(x_values), max(y_values) - min(y_values))
    if span_m > MAX_LOCAL_PLANNER_SPAN_M:
        raise ValueError(
            f"Survey polygon span exceeds local-planner limit of {MAX_LOCAL_PLANNER_SPAN_M:.0f} m"
        )

    gsd_m = _finite(gsd_cm, "GSD") / 100.0
    forward_overlap = _finite(forward_overlap_pct, "forward overlap") / 100.0
    side_overlap = _finite(side_overlap_pct, "side overlap") / 100.0
    direction = _finite(direction_deg, "direction")
    requested_speed = _finite(speed_mps, "speed")
    pitch = _finite(gimbal_pitch_deg, "gimbal pitch")

    if not 0.001 <= gsd_m <= 0.5:
        raise ValueError("GSD must be between 0.1 and 50 cm/px")
    if not 0.0 <= forward_overlap <= 0.95:
        raise ValueError("Forward overlap must be between 0 and 95 percent")
    if not 0.0 <= side_overlap <= 0.95:
        raise ValueError("Side overlap must be between 0 and 95 percent")
    if not 0.0 <= direction < 360.0:
        raise ValueError("Direction must be in [0, 360) degrees")
    if not 0.1 <= requested_speed <= 25.0:
        raise ValueError("Requested speed must be between 0.1 and 25 m/s")
    if not -90.0 <= pitch <= 35.0:
        raise ValueError("Gimbal pitch must be between -90 and +35 degrees")

    horizontal_half_tan = math.tan(math.radians(profile.horizontal_fov_deg) / 2.0)
    vertical_half_tan = math.tan(math.radians(profile.vertical_fov_deg) / 2.0)

    altitude_m = gsd_m * profile.width_px / (2.0 * horizontal_half_tan)
    footprint_width_m = 2.0 * altitude_m * horizontal_half_tan
    footprint_height_m = 2.0 * altitude_m * vertical_half_tan
    trigger_distance_m = footprint_height_m * (1.0 - forward_overlap)
    desired_line_spacing_m = footprint_width_m * (1.0 - side_overlap)

    max_camera_speed_mps = trigger_distance_m / profile.min_interval_s
    effective_speed_mps = min(requested_speed, max_camera_speed_mps)
    speed_limited = effective_speed_mps + 1e-9 < requested_speed

    if overshoot_m is None:
        # A half-footprint lead-in/out lets the first distance-triggered exposure cover the
        # polygon boundary without depending on MAV_CMD_DO_SET_CAM_TRIGG_DIST param3 semantics.
        effective_overshoot_m = footprint_height_m / 2.0
    else:
        effective_overshoot_m = _finite(overshoot_m, "overshoot")
        if effective_overshoot_m < 0.0:
            raise ValueError("Overshoot cannot be negative")

    segments_xy, scan_line_count, actual_line_spacing_m = _scan_segments(
        polygon_xy,
        heading_deg=direction,
        line_spacing_m=desired_line_spacing_m,
        footprint_cross_m=footprint_width_m,
        overshoot_m=effective_overshoot_m,
    )

    items: list[dict[str, Any]] = []

    def append_item(
        command: int,
        *,
        latitude_deg: float = 0.0,
        longitude_deg: float = 0.0,
        altitude: float = 0.0,
        param1: float | None = None,
        param2: float | None = None,
        param3: float | None = None,
        param4: float | None = None,
    ) -> None:
        items.append(
            {
                "seq": len(items),
                "frame": 6,
                "command": command,
                "param1": param1,
                "param2": param2,
                "param3": param3,
                "param4": param4,
                "latitude_deg": latitude_deg,
                "longitude_deg": longitude_deg,
                "altitude_m": altitude,
                "autocontinue": True,
            }
        )

    first_lat, first_lon = inverse(*segments_xy[0][0])
    append_item(
        mavlink_common.MAV_CMD_NAV_TAKEOFF,
        latitude_deg=first_lat,
        longitude_deg=first_lon,
        altitude=altitude_m,
    )
    # MAV_CMD_DO_CHANGE_SPEED param1=1 means groundspeed; Lyrebird consumes param2.
    append_item(
        mavlink_common.MAV_CMD_DO_CHANGE_SPEED,
        param1=1.0,
        param2=effective_speed_mps,
    )
    append_item(
        mavlink_common.MAV_CMD_DO_GIMBAL_MANAGER_PITCHYAW,
        param1=pitch,
    )

    route_xy: list[tuple[float, float]] = []
    active_distance_m = 0.0
    expected_photos = 0

    for start_xy, end_xy in segments_xy:
        start_lat, start_lon = inverse(*start_xy)
        end_lat, end_lon = inverse(*end_xy)

        append_item(
            mavlink_common.MAV_CMD_NAV_WAYPOINT,
            latitude_deg=start_lat,
            longitude_deg=start_lon,
            altitude=altitude_m,
            param1=0.0,
            param3=0.0,
        )
        append_item(
            mavlink_common.MAV_CMD_DO_SET_CAM_TRIGG_DIST,
            param1=trigger_distance_m,
        )
        append_item(
            mavlink_common.MAV_CMD_NAV_WAYPOINT,
            latitude_deg=end_lat,
            longitude_deg=end_lon,
            altitude=altitude_m,
            param1=0.0,
            param3=0.0,
        )
        append_item(
            mavlink_common.MAV_CMD_DO_SET_CAM_TRIGG_DIST,
            param1=0.0,
        )

        segment_distance = _distance(start_xy, end_xy)
        active_distance_m += segment_distance
        expected_photos += max(1, math.ceil(segment_distance / trigger_distance_m))
        route_xy.extend((start_xy, end_xy))

    if len(items) > MAX_MISSION_ITEMS:
        raise ValueError(
            f"Generated survey needs {len(items)} mission items; Lyrebird limit is "
            f"{MAX_MISSION_ITEMS}. Increase GSD/side spacing or split the area."
        )

    route_distance_m = sum(
        _distance(current, following)
        for current, following in zip(route_xy, route_xy[1:])
    )

    planning_context = {
        "schema_version": 1,
        "planner": "M3_CLOUD_GRID",
        "platform": profile.platform,
        "capture_profile": profile.capture_profile,
        "planning_sensor": profile.planning_sensor,
        "geometry_source": profile.geometry_source,
        "parameters": {
            "gsd_cm": gsd_cm,
            "forward_overlap_pct": forward_overlap_pct,
            "side_overlap_pct": side_overlap_pct,
            "direction_deg": direction,
            "requested_speed_mps": requested_speed,
            "gimbal_pitch_deg": pitch,
            "overshoot_m": effective_overshoot_m,
        },
        "derived": {
            "altitude_m": altitude_m,
            "trigger_distance_m": trigger_distance_m,
            "line_spacing_m": actual_line_spacing_m,
            "effective_speed_mps": effective_speed_mps,
            "capture_segment_count": len(segments_xy),
            "expected_photos_upper_bound": expected_photos,
        },
    }
    plan = normalize_plan(items, planning=planning_context)
    compat = compatibility(plan)
    if not compat["wire_ready"]:
        raise ValueError("Generated survey is not compatible with the Lyrebird upload surface")

    warnings: list[str] = []
    if speed_limited:
        warnings.append(
            f"Requested {requested_speed:.2f} m/s exceeds the camera cadence limit; "
            f"plan speed reduced to {effective_speed_mps:.2f} m/s."
        )
    if profile.geometry_source == "DJI_SPEC_12MP_MODE_DERIVED_DIMENSIONS":
        warnings.append(
            "M3T 12 MP planning dimensions are derived; verify actual PHOTO_NORMAL "
            "image dimensions on the target MSDK/firmware before field use."
        )

    return {
        "schema_version": 1,
        "planner": "M3_CLOUD_GRID",
        "profile": profile.as_dict(),
        "input": {
            "polygon": [
                {"latitude_deg": lat, "longitude_deg": lon}
                for lat, lon in vertices
            ],
            "gsd_cm": gsd_cm,
            "forward_overlap_pct": forward_overlap_pct,
            "side_overlap_pct": side_overlap_pct,
            "direction_deg": direction,
            "requested_speed_mps": requested_speed,
            "gimbal_pitch_deg": pitch,
        },
        "geometry": {
            "area_m2": area_m2,
            "altitude_m": altitude_m,
            "footprint_width_m": footprint_width_m,
            "footprint_height_m": footprint_height_m,
            "desired_line_spacing_m": desired_line_spacing_m,
            "actual_line_spacing_m": actual_line_spacing_m,
            "trigger_distance_m": trigger_distance_m,
            "overshoot_m": effective_overshoot_m,
            "scan_line_count": scan_line_count,
            "capture_segment_count": len(segments_xy),
            "route_distance_m": route_distance_m,
            "capture_distance_m": active_distance_m,
            "expected_photos_upper_bound": expected_photos,
        },
        "cadence": {
            "minimum_interval_s": profile.min_interval_s,
            "requested_speed_mps": requested_speed,
            "max_camera_speed_mps": max_camera_speed_mps,
            "effective_speed_mps": effective_speed_mps,
            "effective_trigger_interval_s": trigger_distance_m / effective_speed_mps,
            "speed_limited_by_camera": speed_limited,
        },
        "mission_item_count": len(items),
        "warnings": warnings,
        "plan": plan,
        "compatibility": compat,
    }
