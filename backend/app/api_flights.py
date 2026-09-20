from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.database import session_factory
from app.models import Flight, TelemetrySample


router = APIRouter(prefix="/api/v1/flights", tags=["flights"])


def _summary(flight: Flight) -> dict[str, Any]:
    rtk_percent = None
    if flight.rtk_total_samples > 0:
        rtk_percent = 100.0 * flight.rtk_converged_samples / flight.rtk_total_samples
    return {
        "id": str(flight.id),
        "aircraft_sn": flight.aircraft_sn,
        "gateway_sn": flight.gateway_sn,
        "dji_track_id": flight.dji_track_id,
        "status": flight.status,
        "started_at": flight.started_at.isoformat(),
        "ended_at": flight.ended_at.isoformat() if flight.ended_at else None,
        "duration_s": flight.duration_s,
        "distance_m": flight.distance_m,
        "max_relative_altitude_m": flight.max_relative_altitude_m,
        "max_horizontal_speed_mps": flight.max_horizontal_speed_mps,
        "min_battery_percent": flight.min_battery_percent,
        "rtk_converged_percent": rtk_percent,
        "end_reason": flight.end_reason,
    }


@router.get("")
async def list_flights(
    aircraft_sn: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    statement = select(Flight).order_by(Flight.started_at.desc()).limit(limit)
    if aircraft_sn:
        statement = statement.where(Flight.aircraft_sn == aircraft_sn)
    async with session_factory() as session:
        result = await session.scalars(statement)
        return [_summary(flight) for flight in result.all()]


@router.get("/{flight_id}")
async def flight_detail(flight_id: uuid.UUID) -> dict[str, Any]:
    async with session_factory() as session:
        flight = await session.get(Flight, flight_id)
        if flight is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flight not found")

        async def geometry(column):
            value = await session.scalar(select(func.ST_AsGeoJSON(column)).where(Flight.id == flight_id))
            return json.loads(value) if value else None

        source_rows = await session.scalars(
            select(TelemetrySample.source)
            .where(TelemetrySample.flight_id == flight_id)
            .distinct()
            .order_by(TelemetrySample.source)
        )

        detail = _summary(flight)
        detail.update(
            {
                "sources": source_rows.all(),
                "takeoff_position": await geometry(Flight.takeoff_position),
                "landing_position": await geometry(Flight.landing_position),
                "path": await geometry(Flight.path),
            }
        )
        return detail
