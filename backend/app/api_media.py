from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select

from app.database import session_factory
from app.config import settings
from app.media.datasets import build_dataset_manifest, build_media_datasets
from app.media.matching import match_flight_by_capture_window
from app.media.metadata import asset_metadata_payload
from app.models import Flight, MediaAsset, MediaDatasetRecord


router = APIRouter(prefix="/api/v1/media", tags=["media"])


class DatasetFlightAssignment(BaseModel):
    flight_id: uuid.UUID | None = None


def _asset(asset: MediaAsset) -> dict[str, Any]:
    return {
        "id": str(asset.id),
        "relative_path": asset.relative_path,
        "filename": asset.filename,
        "extension": asset.extension,
        "size_bytes": asset.size_bytes,
        "mtime_ns": asset.mtime_ns,
        "sha256": asset.sha256,
        "capture_time_utc": asset.capture_time_utc.isoformat() if asset.capture_time_utc else None,
        "capture_time_source": asset.capture_time_source,
        "metadata": asset_metadata_payload(asset),
        "platform": asset.platform,
        "media_kind": asset.media_kind,
        "capture_group": asset.capture_group,
        "storage_mode": asset.storage_mode,
        "external_root": asset.external_root,
        "present": asset.present,
        "duplicate_of": str(asset.duplicate_of) if asset.duplicate_of else None,
        "discovered_at": asset.discovered_at.isoformat(),
        "last_seen_at": asset.last_seen_at.isoformat(),
    }


@router.get("")
async def list_media(
    platform: str | None = None,
    media_kind: str | None = None,
    capture_group: str | None = None,
    present: bool | None = True,
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[dict[str, Any]]:
    statement = select(MediaAsset).order_by(
        MediaAsset.capture_group,
        MediaAsset.filename,
    ).limit(limit)

    if platform:
        statement = statement.where(MediaAsset.platform == platform.upper())
    if media_kind:
        statement = statement.where(MediaAsset.media_kind == media_kind.upper())
    if capture_group:
        statement = statement.where(MediaAsset.capture_group == capture_group)
    if present is not None:
        statement = statement.where(MediaAsset.present.is_(present))

    async with session_factory() as session:
        result = await session.scalars(statement)
        return [_asset(asset) for asset in result.all()]


@router.get("/datasets/manifest")
async def media_dataset_manifest(
    prefix: str = Query(min_length=1, max_length=1024),
) -> dict[str, object]:
    normalized = prefix.strip().replace("\\", "/").strip("/")
    if not normalized or ".." in normalized.split("/"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dataset prefix must stay inside the media import root",
        )

    async with session_factory() as session:
        assets = (
            await session.scalars(
                select(MediaAsset).where(
                    MediaAsset.present.is_(True),
                    MediaAsset.duplicate_of.is_(None),
                    (
                        (MediaAsset.relative_path == normalized)
                        | MediaAsset.relative_path.startswith(normalized + "/")
                    ),
                )
            )
        ).all()

    try:
        return build_dataset_manifest(
            assets,
            prefix=normalized,
            import_root=settings.media_import_root,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/datasets/manifest/download")
async def download_media_dataset_manifest(
    prefix: str = Query(min_length=1, max_length=1024),
) -> Response:
    manifest = await media_dataset_manifest(prefix)
    payload = json.dumps(
        manifest,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return Response(
        content=payload,
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="m3-media-dataset-manifest.json"',
            "Content-Length": str(len(payload)),
        },
    )


@router.get("/datasets")
async def media_datasets(
    platform: str | None = None,
) -> list[dict[str, object]]:
    statement = select(MediaAsset).where(
        MediaAsset.present.is_(True),
        MediaAsset.duplicate_of.is_(None),
    )
    if platform:
        statement = statement.where(MediaAsset.platform == platform.upper())

    async with session_factory() as session:
        assets = (await session.scalars(statement)).all()
        summaries = build_media_datasets(assets)

        records_statement = select(MediaDatasetRecord)
        if platform:
            records_statement = records_statement.where(
                MediaDatasetRecord.platform == platform.upper()
            )
        records = (await session.scalars(records_statement)).all()
        records_by_key = {
            (record.platform, record.prefix): record
            for record in records
        }

        flight_ids = {
            record.flight_id
            for record in records
            if record.flight_id is not None
        }
        flights = (
            await session.scalars(select(Flight).where(Flight.id.in_(flight_ids)))
        ).all() if flight_ids else []
        flights_by_id = {flight.id: flight for flight in flights}

        result: list[dict[str, object]] = []
        for summary in summaries:
            item = dict(summary)
            key = (str(summary["platform"]), str(summary["prefix"]))
            record = records_by_key.get(key)
            flight = flights_by_id.get(record.flight_id) if record else None
            item.update(
                {
                    "id": str(record.id) if record else None,
                    "flight_id": str(record.flight_id) if record and record.flight_id else None,
                    "flight_aircraft_sn": flight.aircraft_sn if flight else None,
                    "flight_started_at": flight.started_at.isoformat() if flight else None,
                    "capture_started_at": (
                        record.capture_started_at.isoformat()
                        if record and record.capture_started_at
                        else None
                    ),
                    "capture_ended_at": (
                        record.capture_ended_at.isoformat()
                        if record and record.capture_ended_at
                        else None
                    ),
                    "flight_assignment_source": (
                        record.flight_assignment_source if record else None
                    ),
                    "flight_match_status": record.flight_match_status if record else None,
                    "flight_match_candidates": (
                        record.flight_match_candidates if record else []
                    ),
                }
            )
            result.append(item)
        return result


@router.put("/datasets/{dataset_id}/flight")
async def assign_dataset_flight(
    dataset_id: uuid.UUID,
    body: DatasetFlightAssignment,
) -> dict[str, object]:
    async with session_factory() as session:
        dataset = await session.get(MediaDatasetRecord, dataset_id)
        if dataset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Media dataset not found",
            )

        flight = None
        if body.flight_id is not None:
            flight = await session.get(Flight, body.flight_id)
            if flight is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Flight not found",
                )

        dataset.flight_id = body.flight_id
        dataset.flight_assignment_source = "MANUAL"
        dataset.flight_match_status = "MANUAL"
        dataset.flight_match_candidates = (
            [str(body.flight_id)] if body.flight_id is not None else []
        )
        dataset.updated_at = datetime.now(timezone.utc)
        await session.commit()

        return {
            "id": str(dataset.id),
            "platform": dataset.platform,
            "prefix": dataset.prefix,
            "flight_id": str(dataset.flight_id) if dataset.flight_id else None,
            "flight_aircraft_sn": flight.aircraft_sn if flight else None,
            "flight_started_at": flight.started_at.isoformat() if flight else None,
            "flight_assignment_source": dataset.flight_assignment_source,
            "flight_match_status": dataset.flight_match_status,
            "flight_match_candidates": dataset.flight_match_candidates,
        }


@router.post("/datasets/{dataset_id}/auto-match")
async def auto_match_dataset_flight(
    dataset_id: uuid.UUID,
) -> dict[str, object]:
    async with session_factory() as session:
        dataset = await session.get(MediaDatasetRecord, dataset_id)
        if dataset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Media dataset not found",
            )

        match = await match_flight_by_capture_window(
            session,
            capture_started_at=dataset.capture_started_at,
            capture_ended_at=dataset.capture_ended_at,
            margin_seconds=settings.media_auto_match_margin_seconds,
        )
        dataset.flight_assignment_source = "AUTO"
        dataset.flight_match_status = match.status
        dataset.flight_match_candidates = [
            str(candidate_id) for candidate_id in match.candidate_ids
        ]
        dataset.flight_id = match.flight_id
        dataset.updated_at = datetime.now(timezone.utc)
        await session.commit()

        flight = await session.get(Flight, match.flight_id) if match.flight_id else None
        return {
            "id": str(dataset.id),
            "platform": dataset.platform,
            "prefix": dataset.prefix,
            "flight_id": str(dataset.flight_id) if dataset.flight_id else None,
            "flight_aircraft_sn": flight.aircraft_sn if flight else None,
            "flight_started_at": flight.started_at.isoformat() if flight else None,
            "flight_assignment_source": dataset.flight_assignment_source,
            "flight_match_status": dataset.flight_match_status,
            "flight_match_candidates": dataset.flight_match_candidates,
        }


@router.get("/positions")
async def media_positions(
    platform: str | None = None,
    media_kind: str | None = None,
    capture_group: str | None = None,
    limit: int = Query(default=20_000, ge=1, le=50_000),
) -> dict[str, object]:
    statement = (
        select(MediaAsset)
        .where(
            MediaAsset.present.is_(True),
            MediaAsset.duplicate_of.is_(None),
            MediaAsset.gps_latitude.is_not(None),
            MediaAsset.gps_longitude.is_not(None),
        )
        .order_by(MediaAsset.capture_time_utc, MediaAsset.relative_path)
        .limit(limit)
    )
    if platform:
        statement = statement.where(MediaAsset.platform == platform.upper())
    if media_kind:
        statement = statement.where(MediaAsset.media_kind == media_kind.upper())
    if capture_group:
        statement = statement.where(MediaAsset.capture_group == capture_group)

    async with session_factory() as session:
        assets = (await session.scalars(statement)).all()

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        asset.gps_longitude,
                        asset.gps_latitude,
                    ],
                },
                "properties": {
                    "id": str(asset.id),
                    "filename": asset.filename,
                    "relative_path": asset.relative_path,
                    "platform": asset.platform,
                    "media_kind": asset.media_kind,
                    "capture_group": asset.capture_group,
                    "capture_time_utc": (
                        asset.capture_time_utc.isoformat()
                        if asset.capture_time_utc
                        else None
                    ),
                    "capture_time_source": asset.capture_time_source,
                    "gps_altitude_m": asset.gps_altitude_m,
                    "gps_altitude_ref": asset.gps_altitude_ref,
                    "dji_absolute_altitude_m": asset.dji_absolute_altitude_m,
                    "dji_relative_altitude_m": asset.dji_relative_altitude_m,
                    "metadata_status": asset.metadata_status,
                },
            }
            for asset in assets
        ],
    }


@router.get("/groups")
async def media_groups(
    platform: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[dict[str, Any]]:
    statement = (
        select(
            MediaAsset.capture_group,
            MediaAsset.platform,
            func.count(MediaAsset.id).label("asset_count"),
            func.sum(MediaAsset.size_bytes).label("size_bytes"),
        )
        .where(
            MediaAsset.present.is_(True),
            MediaAsset.capture_group.is_not(None),
        )
        .group_by(MediaAsset.capture_group, MediaAsset.platform)
        .order_by(MediaAsset.capture_group)
        .limit(limit)
    )
    if platform:
        statement = statement.where(MediaAsset.platform == platform.upper())

    async with session_factory() as session:
        rows = (await session.execute(statement)).all()
        return [
            {
                "capture_group": group,
                "platform": item_platform,
                "asset_count": int(asset_count),
                "size_bytes": int(size_bytes or 0),
            }
            for group, item_platform, asset_count, size_bytes in rows
        ]


@router.get("/import/status")
async def import_status(request: Request) -> dict[str, object]:
    importer = getattr(request.app.state, "media_importer", None)
    if importer is None:
        return {
            "enabled": False,
            "status": "disabled",
        }
    current = importer.status()
    return {
        "enabled": True,
        "status": (
            "scanning"
            if current["scan_running"]
            else "ready"
            if current["exists"] and current["readable"]
            else "unavailable"
        ),
        **current,
    }


@router.post("/import/scan")
async def scan_import(request: Request) -> dict[str, object]:
    importer = getattr(request.app.state, "media_importer", None)
    if importer is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Media import is disabled",
        )
    return (await importer.scan()).as_dict()


@router.get("/{asset_id}")
async def media_detail(asset_id: uuid.UUID) -> dict[str, Any]:
    async with session_factory() as session:
        asset = await session.get(MediaAsset, asset_id)
        if asset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Media asset not found",
            )
        return _asset(asset)
