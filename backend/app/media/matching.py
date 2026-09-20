from __future__ import annotations

import math
import re
import statistics
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from typing import Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Flight, TelemetrySample


_DJI_FILENAME_TIME = re.compile(r"(?:^|_)DJI_(?P<stamp>\d{14})(?:_|\.)", re.IGNORECASE)
_EARTH_RADIUS_M = 6_371_008.8


def capture_time_from_filename(
    path: PurePath | str,
    *,
    timezone_name: str,
) -> datetime | None:
    """Parse DJI's YYYYMMDDhhmmss filename timestamp and normalize it to UTC."""

    name = PurePath(path).name
    match = _DJI_FILENAME_TIME.search(name)
    if match is None:
        return None

    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown media filename timezone: {timezone_name}") from exc

    local = datetime.strptime(match.group("stamp"), "%Y%m%d%H%M%S").replace(tzinfo=zone)
    return local.astimezone(timezone.utc)


@dataclass(frozen=True)
class CandidateEvidence:
    flight_id: str
    aircraft_sn: str
    track_points: int
    gps_points_sampled: int
    gps_points_within: int
    gps_within_fraction: float | None
    timed_points_sampled: int
    timed_points_paired: int
    median_time_delta_s: float | None
    median_distance_m: float | None
    max_distance_m: float | None
    validation_mode: str
    spatial_status: str
    spatial_pass: bool


@dataclass(frozen=True)
class FlightMatch:
    status: str
    flight_id: uuid.UUID | None
    candidate_ids: tuple[uuid.UUID, ...]
    details: dict[str, object]


def _sample_evenly[T](items: Sequence[T], maximum: int) -> list[T]:
    if maximum <= 0 or len(items) <= maximum:
        return list(items)
    if maximum == 1:
        return [items[len(items) // 2]]

    indexes = {
        round(index * (len(items) - 1) / (maximum - 1))
        for index in range(maximum)
    }
    return [items[index] for index in sorted(indexes)]


def _haversine_m(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    phi_a = math.radians(latitude_a)
    phi_b = math.radians(latitude_b)
    d_phi = phi_b - phi_a
    d_lambda = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(value)))


def _distance_to_segment_m(
    latitude: float,
    longitude: float,
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Local tangent-plane distance from a WGS84 point to a short flight segment."""

    latitude_rad = math.radians(latitude)
    cos_latitude = max(0.01, abs(math.cos(latitude_rad)))

    def local(point: tuple[float, float]) -> tuple[float, float]:
        point_latitude, point_longitude = point
        x = math.radians(point_longitude - longitude) * cos_latitude * _EARTH_RADIUS_M
        y = math.radians(point_latitude - latitude) * _EARTH_RADIUS_M
        return x, y

    x1, y1 = local(start)
    x2, y2 = local(end)
    dx = x2 - x1
    dy = y2 - y1
    denominator = dx * dx + dy * dy
    if denominator == 0:
        return math.hypot(x1, y1)

    projection = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / denominator))
    closest_x = x1 + projection * dx
    closest_y = y1 + projection * dy
    return math.hypot(closest_x, closest_y)


def _distance_to_track_m(
    point: tuple[float, float],
    track: Sequence[tuple[float, float]],
) -> float:
    latitude, longitude = point
    if not track:
        return math.inf
    if len(track) == 1:
        return _haversine_m(latitude, longitude, track[0][0], track[0][1])

    return min(
        _distance_to_segment_m(latitude, longitude, start, end)
        for start, end in zip(track, track[1:])
    )


async def _flight_track(
    session: AsyncSession,
    flight_id: uuid.UUID,
    *,
    max_points: int = 1000,
) -> list[tuple[datetime, float, float]]:
    rows = (
        await session.execute(
            select(
                TelemetrySample.recorded_at,
                func.ST_Y(TelemetrySample.position).label("latitude"),
                func.ST_X(TelemetrySample.position).label("longitude"),
            )
            .where(
                TelemetrySample.flight_id == flight_id,
                TelemetrySample.position.is_not(None),
            )
            .order_by(TelemetrySample.recorded_at, TelemetrySample.id)
        )
    ).all()

    points = [
        (recorded_at, float(latitude), float(longitude))
        for recorded_at, latitude, longitude in rows
        if recorded_at is not None and latitude is not None and longitude is not None
    ]
    return _sample_evenly(points, max_points)


async def match_flight_by_capture_window(
    session: AsyncSession,
    *,
    capture_started_at: datetime | None,
    capture_ended_at: datetime | None,
    margin_seconds: float,
    gps_points: Sequence[tuple[float, float]] = (),
    capture_points: Sequence[tuple[datetime | None, float, float]] = (),
    max_distance_m: float = 100.0,
    min_gps_fraction: float = 0.8,
    max_gps_samples: int = 64,
    max_sample_time_delta_seconds: float = 5.0,
) -> FlightMatch:
    """Match a dataset to a flight using time first and GPS as conservative validation."""

    validation_points = (
        list(capture_points)
        if capture_points
        else [(None, latitude, longitude) for latitude, longitude in gps_points]
    )
    base_details: dict[str, object] = {
        "strategy": "TIME_THEN_GPS",
        "time_margin_seconds": max(0.0, margin_seconds),
        "gps_max_distance_m": max(0.0, max_distance_m),
        "gps_min_fraction": max(0.0, min(1.0, min_gps_fraction)),
        "gps_max_sample_time_delta_seconds": max(
            0.0,
            max_sample_time_delta_seconds,
        ),
        "gps_points_available": len(validation_points),
        "gps_points_sampled": 0,
        "candidates": [],
    }

    if capture_started_at is None or capture_ended_at is None:
        return FlightMatch("NO_CAPTURE_TIME", None, (), base_details)

    margin = timedelta(seconds=max(0.0, margin_seconds))
    search_start = capture_started_at - margin
    search_end = capture_ended_at + margin

    candidates = (
        await session.scalars(
            select(Flight)
            .where(
                Flight.started_at <= search_end,
                or_(Flight.ended_at.is_(None), Flight.ended_at >= search_start),
            )
            .order_by(Flight.started_at, Flight.id)
        )
    ).all()

    contained: list[Flight] = []
    for flight in candidates:
        start_bound = flight.started_at - margin
        end_bound = (flight.ended_at + margin) if flight.ended_at else search_end
        if capture_started_at >= start_bound and capture_ended_at <= end_bound:
            contained.append(flight)

    ids = tuple(flight.id for flight in contained)
    if not ids:
        return FlightMatch("NO_MATCH", None, (), base_details)

    sampled_gps = _sample_evenly(validation_points, max(1, max_gps_samples))
    base_details["gps_points_sampled"] = len(sampled_gps)

    if not sampled_gps:
        base_details["validation"] = "TIME_ONLY"
        if len(ids) == 1:
            return FlightMatch("MATCHED_TIME_ONLY", ids[0], ids, base_details)
        return FlightMatch("AMBIGUOUS_TIME", None, ids, base_details)

    threshold = max(0.0, max_distance_m)
    required_fraction = max(0.0, min(1.0, min_gps_fraction))
    evidence: list[CandidateEvidence] = []
    passing: list[uuid.UUID] = []

    time_tolerance = max(0.0, max_sample_time_delta_seconds)

    for flight in contained:
        track = await _flight_track(session, flight.id)
        if not track:
            item = CandidateEvidence(
                flight_id=str(flight.id),
                aircraft_sn=flight.aircraft_sn,
                track_points=0,
                gps_points_sampled=len(sampled_gps),
                gps_points_within=0,
                gps_within_fraction=None,
                timed_points_sampled=sum(1 for captured_at, _, _ in sampled_gps if captured_at is not None),
                timed_points_paired=0,
                median_time_delta_s=None,
                median_distance_m=None,
                max_distance_m=None,
                validation_mode="TIMED_GPS" if any(captured_at is not None for captured_at, _, _ in sampled_gps) else "TRACK_GPS",
                spatial_status="NO_FLIGHT_GPS",
                spatial_pass=False,
            )
            evidence.append(item)
            continue

        track_coordinates = [(latitude, longitude) for _, latitude, longitude in track]
        distances: list[float] = []
        time_deltas: list[float] = []
        within = 0
        timed_sampled = 0
        timed_paired = 0
        untimed_sampled = 0

        for captured_at, latitude, longitude in sampled_gps:
            if captured_at is None:
                untimed_sampled += 1
                distance = _distance_to_track_m(
                    (latitude, longitude),
                    track_coordinates,
                )
                distances.append(distance)
                if distance <= threshold:
                    within += 1
                continue

            timed_sampled += 1
            nearest = min(
                track,
                key=lambda item: abs((item[0] - captured_at).total_seconds()),
            )
            time_delta = abs((nearest[0] - captured_at).total_seconds())
            time_deltas.append(time_delta)
            if time_delta > time_tolerance:
                continue

            timed_paired += 1
            distance = _haversine_m(
                latitude,
                longitude,
                nearest[1],
                nearest[2],
            )
            distances.append(distance)
            if distance <= threshold:
                within += 1

        fraction = within / len(sampled_gps)
        spatial_pass = fraction >= required_fraction
        if spatial_pass:
            passing.append(flight.id)

        finite_distances = [distance for distance in distances if math.isfinite(distance)]
        if timed_sampled and untimed_sampled:
            validation_mode = "TIMED_AND_TRACK_GPS"
        elif timed_sampled:
            validation_mode = "TIMED_GPS"
        else:
            validation_mode = "TRACK_GPS"

        evidence.append(
            CandidateEvidence(
                flight_id=str(flight.id),
                aircraft_sn=flight.aircraft_sn,
                track_points=len(track),
                gps_points_sampled=len(sampled_gps),
                gps_points_within=within,
                gps_within_fraction=round(fraction, 6),
                timed_points_sampled=timed_sampled,
                timed_points_paired=timed_paired,
                median_time_delta_s=(
                    round(statistics.median(time_deltas), 3)
                    if time_deltas
                    else None
                ),
                median_distance_m=(
                    round(statistics.median(finite_distances), 3)
                    if finite_distances
                    else None
                ),
                max_distance_m=(
                    round(max(finite_distances), 3)
                    if finite_distances
                    else None
                ),
                validation_mode=validation_mode,
                spatial_status="PASS" if spatial_pass else "REJECT",
                spatial_pass=spatial_pass,
            )
        )

    base_details["validation"] = "TIME_AND_GPS"
    base_details["candidates"] = [asdict(item) for item in evidence]

    if len(passing) == 1:
        return FlightMatch("MATCHED_TIME_GPS", passing[0], ids, base_details)
    if len(passing) > 1:
        return FlightMatch("AMBIGUOUS_GPS", None, ids, base_details)

    if evidence and all(item.track_points == 0 for item in evidence):
        return FlightMatch("GPS_UNVERIFIED", None, ids, base_details)
    return FlightMatch("GPS_REJECTED", None, ids, base_details)
