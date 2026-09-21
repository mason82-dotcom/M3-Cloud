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
    stored_assets_per_exposure: int
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
        stored_assets_per_exposure=1,
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
        stored_assets_per_exposure=1,
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
        stored_assets_per_exposure=6,
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
) -> tuple[list[tuple[float, float]], Any, Any]:
    lat0 = sum(lat for lat, _ in points) / len(points)
    lon0 = sum(lon for _, lon in points) / len(points)
    cos_lat0 = math.cos(math.radians(lat0))
    if abs(cos_lat0) < 1e-8:
        raise ValueError("Survey polygon is too close to a geographic pole")

    def project(lat: float, lon: float) -> tuple[float, float]:
        return (
            EARTH_RADIUS_M * cos_lat0 * math.radians(lon - lon0),
            EARTH_RADIUS_M * math.radians(lat - lat0),
        )

    projected = [project(lat, lon) for lat, lon in points]

    def inverse(x: float, y: float) -> tuple[float, float]:
        return (
            lat0 + math.degrees(y / EARTH_RADIUS_M),
            lon0 + math.degrees(x / (EARTH_RADIUS_M * cos_lat0)),
        )

    return projected, project, inverse


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


def _route_points(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
) -> list[tuple[float, float]]:
    return [point for segment in segments for point in segment]


def _route_distance(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
) -> float:
    points = _route_points(segments)
    return sum(
        _distance(current, following)
        for current, following in zip(points, points[1:])
    )


def _reverse_segments(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return [(end, start) for start, end in reversed(segments)]


def _candidate_headings(
    polygon_xy: list[tuple[float, float]],
    requested_direction_deg: float,
) -> list[float]:
    # A coarse global sweep prevents pathological edge-only choices on irregular polygons.
    # Exact polygon-edge bearings are added so rectangles and parcel boundaries can align exactly.
    headings = {float(value) for value in range(0, 180, 5)}
    headings.add(round(requested_direction_deg % 180.0, 6))
    closed = polygon_xy + [polygon_xy[0]]
    edge_candidates: list[tuple[float, float]] = []
    for current, following in zip(closed, closed[1:]):
        dx = following[0] - current[0]
        dy = following[1] - current[1]
        length = math.hypot(dx, dy)
        if length < MIN_SEGMENT_M:
            continue
        heading = math.degrees(math.atan2(dx, dy)) % 180.0
        edge_candidates.append((length, round(heading, 6)))

    # Noisy imported boundaries may contain hundreds of tiny edge bearings. The 5-degree
    # sweep already gives global coverage; exact alignment is only useful for dominant edges.
    for _, heading in sorted(edge_candidates, reverse=True)[:24]:
        headings.add(heading)
    return sorted(headings)


def _orient_for_reference(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
    start_reference_xy: tuple[float, float] | None,
    *,
    return_reference_xy: tuple[float, float] | None,
) -> tuple[
    list[tuple[tuple[float, float], tuple[float, float]]],
    bool,
    float,
    float,
]:
    if start_reference_xy is None and return_reference_xy is None:
        return segments, False, 0.0, 0.0

    def external_distance(
        candidate: list[tuple[tuple[float, float], tuple[float, float]]],
    ) -> tuple[float, float, float]:
        ingress = (
            _distance(start_reference_xy, candidate[0][0])
            if start_reference_xy is not None
            else 0.0
        )
        egress = (
            _distance(candidate[-1][1], return_reference_xy)
            if return_reference_xy is not None
            else 0.0
        )
        return ingress + egress, ingress, egress

    forward_total, forward_ingress, forward_egress = external_distance(segments)
    reversed_segments = _reverse_segments(segments)
    reverse_total, reverse_ingress, reverse_egress = external_distance(reversed_segments)

    # When two traversals have the same total external travel, prefer the shorter ingress so
    # the first survey leg begins nearer the aircraft's current/start reference.
    if (
        reverse_total + 1e-9 < forward_total
        or (
            abs(reverse_total - forward_total) <= 1e-9
            and reverse_ingress + 1e-9 < forward_ingress
        )
    ):
        return reversed_segments, True, reverse_ingress, reverse_egress
    return segments, False, forward_ingress, forward_egress


def _select_scan_segments(
    polygon_xy: list[tuple[float, float]],
    *,
    requested_direction_deg: float,
    optimize_direction: bool,
    line_spacing_m: float,
    footprint_cross_m: float,
    overshoot_m: float,
    start_reference_xy: tuple[float, float] | None,
    return_reference_xy: tuple[float, float] | None,
    max_segments: int | None = None,
) -> tuple[
    list[tuple[tuple[float, float], tuple[float, float]]],
    int,
    float,
    float,
    bool,
    float,
    float,
    int,
]:
    headings = (
        _candidate_headings(polygon_xy, requested_direction_deg)
        if optimize_direction
        else [requested_direction_deg]
    )
    best: tuple[
        tuple[int, float, int, float],
        list[tuple[tuple[float, float], tuple[float, float]]],
        int,
        float,
        float,
        bool,
        float,
        float,
    ] | None = None

    for heading in headings:
        segments, scan_line_count, actual_spacing = _scan_segments(
            polygon_xy,
            heading_deg=heading,
            line_spacing_m=line_spacing_m,
            footprint_cross_m=footprint_cross_m,
            overshoot_m=overshoot_m,
        )
        oriented, reversed_for_reference, ingress_m, egress_m = _orient_for_reference(
            segments,
            start_reference_xy,
            return_reference_xy=return_reference_xy,
        )
        route_m = _route_distance(oriented)
        score = route_m + ingress_m + egress_m
        # A route that fits Lyrebird's mission-item limit always wins over an infeasible one.
        # Within the same feasibility class, prefer shorter travel, fewer segments, then the
        # lower heading for deterministic output when geometrically equivalent candidates tie.
        over_limit = int(max_segments is not None and len(oriented) > max_segments)
        rank = (over_limit, score, len(oriented), heading)
        if best is None or rank < best[0]:
            best = (
                rank,
                oriented,
                scan_line_count,
                actual_spacing,
                heading,
                reversed_for_reference,
                ingress_m,
                egress_m,
            )

    if best is None:
        raise ValueError("Survey optimizer produced no flyable route")
    _, segments, line_count, spacing, heading, reversed_route, ingress_m, egress_m = best
    return (
        segments,
        line_count,
        spacing,
        heading,
        reversed_route,
        ingress_m,
        egress_m,
        len(headings),
    )


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
    finish_action: str = "RTH",
    optimize_direction: bool = False,
    start_reference: tuple[float, float] | None = None,
    home_reference: tuple[float, float] | None = None,
) -> dict[str, Any]:
    profile = planning_profile(platform, capture_profile)
    vertices = _normalise_polygon(polygon)
    polygon_xy, project, inverse = _local_projection(vertices)
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
    finish = str(finish_action).strip().upper()

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
    if finish not in {"RTH", "LAND", "NONE"}:
        raise ValueError("Finish action must be one of RTH, LAND, or NONE")

    reference_geo: tuple[float, float] | None = None
    reference_xy: tuple[float, float] | None = None
    if start_reference is not None:
        reference_lat = _finite(start_reference[0], "start reference latitude")
        reference_lon = _finite(start_reference[1], "start reference longitude")
        if not -90.0 <= reference_lat <= 90.0:
            raise ValueError("Start reference latitude out of range")
        if not -180.0 <= reference_lon <= 180.0:
            raise ValueError("Start reference longitude out of range")
        reference_geo = (reference_lat, reference_lon)
        reference_xy = project(reference_lat, reference_lon)

    home_reference_geo: tuple[float, float] | None = None
    home_reference_xy: tuple[float, float] | None = None
    if home_reference is not None:
        home_lat = _finite(home_reference[0], "home reference latitude")
        home_lon = _finite(home_reference[1], "home reference longitude")
        if not -90.0 <= home_lat <= 90.0:
            raise ValueError("Home reference latitude out of range")
        if not -180.0 <= home_lon <= 180.0:
            raise ValueError("Home reference longitude out of range")
        home_reference_geo = (home_lat, home_lon)
        home_reference_xy = project(home_lat, home_lon)

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

    terminal_item_count = 1 if finish in {"RTH", "LAND"} else 0
    max_capture_segments = max(
        0,
        (MAX_MISSION_ITEMS - 3 - terminal_item_count) // 4,
    )

    (
        segments_xy,
        scan_line_count,
        actual_line_spacing_m,
        effective_direction_deg,
        reversed_for_reference,
        ingress_distance_m,
        return_distance_m,
        optimization_candidate_count,
    ) = _select_scan_segments(
        polygon_xy,
        requested_direction_deg=direction,
        optimize_direction=bool(optimize_direction),
        line_spacing_m=desired_line_spacing_m,
        footprint_cross_m=footprint_width_m,
        overshoot_m=effective_overshoot_m,
        start_reference_xy=reference_xy,
        return_reference_xy=(
            home_reference_xy if home_reference_xy is not None else reference_xy
        ) if finish == "RTH" else None,
        max_segments=max_capture_segments,
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
        # Conservative resource bound: DJI's distance trigger can produce an exposure at/near
        # a segment boundary depending on executor semantics. One extra exposure per independent
        # trigger span avoids under-estimating storage and processing load.
        expected_photos += max(
            1,
            math.ceil(segment_distance / trigger_distance_m) + 1,
        )
        route_xy.extend((start_xy, end_xy))

    # The DJI-native compiler maps a trailing RTL/LAND command to the wayline finishAction.
    # Keep RTH as the planner default so a generated survey never silently ends in NO_ACTION.
    if finish == "RTH":
        append_item(mavlink_common.MAV_CMD_NAV_RETURN_TO_LAUNCH)
    elif finish == "LAND":
        append_item(mavlink_common.MAV_CMD_NAV_LAND)

    if len(items) > MAX_MISSION_ITEMS:
        raise ValueError(
            f"Generated survey needs {len(items)} mission items; Lyrebird limit is "
            f"{MAX_MISSION_ITEMS}. Increase GSD/side spacing or split the area."
        )

    route_distance_m = sum(
        _distance(current, following)
        for current, following in zip(route_xy, route_xy[1:])
    )
    total_planned_distance_m = (
        route_distance_m + ingress_distance_m + return_distance_m
    )
    max_reference_distance_m = (
        max(_distance(reference_xy, point) for point in route_xy)
        if reference_xy is not None and route_xy
        else None
    )
    max_home_distance_m = (
        max(_distance(home_reference_xy, point) for point in route_xy)
        if home_reference_xy is not None and route_xy
        else None
    )
    # DJI's native fly-to-wayline transition is configured at 10 m/s. Never assume a faster
    # ingress/RTH contribution just because the survey legs themselves can run faster.
    transit_speed_mps = min(effective_speed_mps, 10.0)
    nominal_route_time_s = route_distance_m / effective_speed_mps
    nominal_transit_time_s = (
        ingress_distance_m + return_distance_m
    ) / transit_speed_mps
    nominal_total_time_s = nominal_route_time_s + nominal_transit_time_s
    nominal_capture_time_s = active_distance_m / effective_speed_mps
    expected_media_assets_upper_bound = (
        expected_photos * profile.stored_assets_per_exposure
    )

    planning_context = {
        "schema_version": 1,
        "planner": "M3_CLOUD_GRID",
        "platform": profile.platform,
        "capture_profile": profile.capture_profile,
        "planning_sensor": profile.planning_sensor,
        "geometry_source": profile.geometry_source,
        "polygon": [
            {"latitude_deg": lat, "longitude_deg": lon}
            for lat, lon in vertices
        ],
        "parameters": {
            "gsd_cm": gsd_cm,
            "forward_overlap_pct": forward_overlap_pct,
            "side_overlap_pct": side_overlap_pct,
            "direction_deg": effective_direction_deg,
            "requested_direction_deg": direction,
            "optimize_direction": bool(optimize_direction),
            "requested_speed_mps": requested_speed,
            "gimbal_pitch_deg": pitch,
            "overshoot_m": effective_overshoot_m,
            "finish_action": finish,
            "start_reference_latitude_deg": (
                reference_geo[0] if reference_geo is not None else None
            ),
            "start_reference_longitude_deg": (
                reference_geo[1] if reference_geo is not None else None
            ),
            "home_reference_latitude_deg": (
                home_reference_geo[0] if home_reference_geo is not None else None
            ),
            "home_reference_longitude_deg": (
                home_reference_geo[1] if home_reference_geo is not None else None
            ),
        },
        "derived": {
            "altitude_m": altitude_m,
            "trigger_distance_m": trigger_distance_m,
            "line_spacing_m": actual_line_spacing_m,
            "effective_speed_mps": effective_speed_mps,
            "capture_segment_count": len(segments_xy),
            "expected_photos_upper_bound": expected_photos,
            "expected_media_assets_upper_bound": expected_media_assets_upper_bound,
            "nominal_route_time_s": nominal_route_time_s,
            "nominal_transit_time_s": nominal_transit_time_s,
            "nominal_total_time_s": nominal_total_time_s,
            "transit_speed_mps": transit_speed_mps,
            "ingress_distance_m": ingress_distance_m,
            "return_distance_m": return_distance_m,
            "total_planned_distance_m": total_planned_distance_m,
            "max_reference_distance_m": max_reference_distance_m,
            "max_home_distance_m": max_home_distance_m,
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
    if finish == "NONE":
        warnings.append(
            "No terminal RTL/LAND action is selected; DJI-native execution will not receive "
            "an explicit planner finish action."
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
            "direction_deg": effective_direction_deg,
            "requested_direction_deg": direction,
            "optimize_direction": bool(optimize_direction),
            "requested_speed_mps": requested_speed,
            "gimbal_pitch_deg": pitch,
            "finish_action": finish,
            "start_reference": (
                {
                    "latitude_deg": reference_geo[0],
                    "longitude_deg": reference_geo[1],
                }
                if reference_geo is not None
                else None
            ),
            "home_reference": (
                {
                    "latitude_deg": home_reference_geo[0],
                    "longitude_deg": home_reference_geo[1],
                }
                if home_reference_geo is not None
                else None
            ),
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
            "ingress_distance_m": ingress_distance_m,
            "return_distance_m": return_distance_m,
            "total_planned_distance_m": total_planned_distance_m,
            "max_reference_distance_m": max_reference_distance_m,
            "max_home_distance_m": max_home_distance_m,
            "capture_distance_m": active_distance_m,
            "expected_photos_upper_bound": expected_photos,
            "expected_media_assets_upper_bound": expected_media_assets_upper_bound,
            "stored_assets_per_exposure": profile.stored_assets_per_exposure,
            "nominal_route_time_s": nominal_route_time_s,
            "nominal_transit_time_s": nominal_transit_time_s,
            "nominal_total_time_s": nominal_total_time_s,
            "transit_speed_mps": transit_speed_mps,
            "nominal_capture_time_s": nominal_capture_time_s,
        },
        "optimization": {
            "enabled": bool(optimize_direction),
            "candidate_count": optimization_candidate_count,
            "requested_direction_deg": direction,
            "selected_direction_deg": effective_direction_deg,
            "reversed_for_reference": reversed_for_reference,
            "reference_used": reference_geo is not None,
            "score_distance_m": total_planned_distance_m,
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
