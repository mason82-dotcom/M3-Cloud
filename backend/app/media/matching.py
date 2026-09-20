from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Flight


_DJI_FILENAME_TIME = re.compile(r"(?:^|_)DJI_(?P<stamp>\d{14})(?:_|\.)", re.IGNORECASE)


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
class FlightMatch:
    status: str
    flight_id: uuid.UUID | None
    candidate_ids: tuple[uuid.UUID, ...]


async def match_flight_by_capture_window(
    session: AsyncSession,
    *,
    capture_started_at: datetime | None,
    capture_ended_at: datetime | None,
    margin_seconds: float,
) -> FlightMatch:
    if capture_started_at is None or capture_ended_at is None:
        return FlightMatch("NO_CAPTURE_TIME", None, ())

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
    if len(ids) == 1:
        return FlightMatch("MATCHED", ids[0], ids)
    if len(ids) > 1:
        return FlightMatch("AMBIGUOUS", None, ids)
    return FlightMatch("NO_MATCH", None, ())
