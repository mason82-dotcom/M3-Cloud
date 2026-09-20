from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.database import session_factory
from app.config import settings
from app.media.datasets import build_dataset_manifest, build_media_datasets
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
        dataset.updated_at = datetime.now(timezone.utc)
        await session.commit()

        return {
            "id": str(dataset.id),
            "platform": dataset.platform,
            "prefix": dataset.prefix,
            "flight_id": str(dataset.flight_id) if dataset.flight_id else None,
            "flight_aircraft_sn": flight.aircraft_sn if flight else None,
            "flight_started_at": flight.started_at.isoformat() if flight else None,
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
