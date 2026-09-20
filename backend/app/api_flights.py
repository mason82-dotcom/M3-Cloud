from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.database import session_factory
from app.models import (
    Flight,
    MediaDatasetRecord,
    ProcessingJob,
    TelemetrySample,
)


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
        "survey_id": str(flight.survey_id) if flight.survey_id else None,
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

        media_datasets = (
            await session.scalars(
                select(MediaDatasetRecord)
                .where(MediaDatasetRecord.flight_id == flight_id)
                .order_by(MediaDatasetRecord.platform, MediaDatasetRecord.prefix)
            )
        ).all()
        processing_jobs = (
            await session.scalars(
                select(ProcessingJob)
                .where(ProcessingJob.flight_id == flight_id)
                .order_by(ProcessingJob.created_at.desc())
            )
        ).all()

        detail = _summary(flight)
        detail.update(
            {
                "sources": source_rows.all(),
                "takeoff_position": await geometry(Flight.takeoff_position),
                "landing_position": await geometry(Flight.landing_position),
                "path": await geometry(Flight.path),
                "media_datasets": [
                    {
                        "id": str(dataset.id),
                        "platform": dataset.platform,
                        "prefix": dataset.prefix,
                        "title": dataset.title,
                        "present": dataset.present,
                    }
                    for dataset in media_datasets
                ],
                "processing_jobs": [
                    {
                        "id": str(job.id),
                        "kind": job.kind,
                        "status": job.status,
                        "name": job.name,
                        "platform": job.platform,
                        "input_prefix": job.input_prefix,
                    }
                    for job in processing_jobs
                ],
            }
        )
        return detail


@router.get("/{flight_id}/samples")
async def flight_samples(
    flight_id: uuid.UUID,
    limit: int = Query(default=10_000, ge=1, le=20_000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Return ordered replay samples with explicit source/positioning provenance."""

    async with session_factory() as session:
        flight = await session.get(Flight, flight_id)
        if flight is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Flight not found",
            )

        total = await session.scalar(
            select(func.count(TelemetrySample.id)).where(
                TelemetrySample.flight_id == flight_id
            )
        )
        total = int(total or 0)

        statement = (
            select(
                TelemetrySample,
                func.ST_X(TelemetrySample.position).label("longitude"),
                func.ST_Y(TelemetrySample.position).label("latitude"),
                func.ST_Z(TelemetrySample.position).label("position_z_m"),
            )
            .where(TelemetrySample.flight_id == flight_id)
            .order_by(TelemetrySample.recorded_at, TelemetrySample.id)
            .offset(offset)
            .limit(limit)
        )
        rows = (await session.execute(statement)).all()

        samples = []
        for sample, longitude, latitude, position_z_m in rows:
            samples.append(
                {
                    "id": sample.id,
                    "recorded_at": sample.recorded_at.isoformat(),
                    "source_timestamp_ms": sample.source_timestamp_ms,
                    "source": sample.source,
                    "longitude": longitude,
                    "latitude": latitude,
                    "position_z_m": position_z_m,
                    "relative_altitude_m": sample.relative_altitude_m,
                    "ellipsoid_height_m": sample.ellipsoid_height_m,
                    "horizontal_speed_mps": sample.horizontal_speed_mps,
                    "vertical_speed_mps": sample.vertical_speed_mps,
                    "heading_deg": sample.heading_deg,
                    "mode_code": sample.mode_code,
                    "battery_percent": sample.battery_percent,
                    "position_convergence": sample.position_convergence,
                    "gps_satellites": sample.gps_satellites,
                    "rtk_satellites": sample.rtk_satellites,
                }
            )

        return {
            "flight_id": str(flight_id),
            "total": total,
            "count": len(samples),
            "offset": offset,
            "truncated": offset + len(samples) < total,
            "samples": samples,
        }
