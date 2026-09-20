from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path, Request, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.database import session_factory
from app.models import ProcessingJob, ProcessingResult
from app.processing.profiles import DEFAULT_PROFILE, profile_catalog
from app.storage import create_storage_client


router = APIRouter(prefix="/api/v1/processing", tags=["processing"])


class WebODMJobRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    input_prefix: str = Field(min_length=1, max_length=1024)
    platform: str | None = None
    profile: str = DEFAULT_PROFILE


class ThermogramJobRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    input_prefix: str = Field(min_length=1, max_length=1024)


class ExternalJobStatusRequest(BaseModel):
    status: Literal["RUNNING_EXTERNAL", "COMPLETED_EXTERNAL", "FAILED_EXTERNAL"]
    error: str | None = Field(default=None, max_length=2000)


def _job(job: ProcessingJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "kind": job.kind,
        "status": job.status,
        "name": job.name,
        "input_prefix": job.input_prefix,
        "platform": job.platform,
        "flight_id": str(job.flight_id) if job.flight_id else None,
        "media_kinds": job.media_kinds,
        "options": job.options,
        "image_count": job.image_count,
        "uploaded_count": job.uploaded_count,
        "progress": job.progress,
        "remote_project_id": job.remote_project_id,
        "remote_task_id": job.remote_task_id,
        "remote_status": job.remote_status,
        "available_assets": job.available_assets,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "updated_at": job.updated_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.get("/profiles")
async def processing_profiles() -> list[dict[str, Any]]:
    return profile_catalog()


@router.get("/jobs")
async def list_processing_jobs() -> list[dict[str, Any]]:
    async with session_factory() as session:
        jobs = (
            await session.scalars(
                select(ProcessingJob).order_by(ProcessingJob.created_at.desc()).limit(200)
            )
        ).all()
        return [_job(job) for job in jobs]


@router.get("/jobs/{job_id}")
async def processing_job(job_id: uuid.UUID) -> dict[str, Any]:
    async with session_factory() as session:
        job = await session.get(ProcessingJob, job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Processing job not found",
            )
        return _job(job)


def _result(result: ProcessingResult) -> dict[str, Any]:
    return {
        "id": str(result.id),
        "job_id": str(result.job_id),
        "asset_name": result.asset_name,
        "bucket": result.bucket,
        "object_key": result.object_key,
        "size_bytes": result.size_bytes,
        "sha256": result.sha256,
        "content_type": result.content_type,
        "details": result.details or {},
        "created_at": result.created_at.isoformat(),
    }


@router.get("/jobs/{job_id}/results")
async def processing_results(job_id: uuid.UUID) -> list[dict[str, Any]]:
    async with session_factory() as session:
        results = (
            await session.scalars(
                select(ProcessingResult)
                .where(ProcessingResult.job_id == job_id)
                .order_by(ProcessingResult.asset_name)
            )
        ).all()
        return [_result(result) for result in results]


@router.get("/jobs/{job_id}/results/{result_id}/download")
async def download_processing_result(
    job_id: uuid.UUID,
    result_id: uuid.UUID,
) -> StreamingResponse:
    async with session_factory() as session:
        result = await session.get(ProcessingResult, result_id)
        if result is None or result.job_id != job_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Processing result not found",
            )
        bucket = result.bucket
        object_key = result.object_key
        asset_name = result.asset_name
        content_type = result.content_type
        size_bytes = result.size_bytes

    client = create_storage_client()
    try:
        response = client.get_object(Bucket=bucket, Key=object_key)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Result object unavailable: {type(exc).__name__}",
        ) from exc

    body = response["Body"]

    def chunks():
        try:
            yield from body.iter_chunks(chunk_size=1024 * 1024)
        finally:
            body.close()

    return StreamingResponse(
        chunks(),
        media_type=content_type,
        headers={
            "Content-Length": str(size_bytes),
            "Content-Disposition": f'attachment; filename="{asset_name}"',
        },
    )


@router.post("/webodm", status_code=status.HTTP_202_ACCEPTED)
async def create_webodm_job(
    body: WebODMJobRequest,
    request: Request,
) -> dict[str, Any]:
    manager = request.app.state.processing_manager
    try:
        job = await manager.create_webodm_job(
            name=body.name,
            input_prefix=body.input_prefix,
            platform=body.platform,
            profile=body.profile,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return _job(job)


@router.post("/thermogram", status_code=status.HTTP_201_CREATED)
async def create_thermogram_job(
    body: ThermogramJobRequest,
    request: Request,
) -> dict[str, Any]:
    manager = request.app.state.processing_manager
    try:
        job = await manager.create_thermogram_job(
            name=body.name,
            input_prefix=body.input_prefix,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return _job(job)


@router.get("/jobs/{job_id}/handoff")
async def processing_handoff(
    job_id: uuid.UUID,
    request: Request,
) -> dict[str, object]:
    manager = request.app.state.processing_manager
    try:
        return await manager.thermogram_handoff(job_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/jobs/{job_id}/handoff/download")
async def download_processing_handoff(
    job_id: uuid.UUID,
    request: Request,
) -> Response:
    manifest = await processing_handoff(job_id, request)
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
            "Content-Disposition": 'attachment; filename="m3t-thermogram-handoff.json"',
            "Content-Length": str(len(payload)),
        },
    )


@router.post("/jobs/{job_id}/external-status")
async def update_external_processing_status(
    job_id: uuid.UUID,
    body: ExternalJobStatusRequest,
    request: Request,
) -> dict[str, Any]:
    manager = request.app.state.processing_manager
    try:
        job = await manager.update_external_job(
            job_id,
            new_status=body.status,
            error=body.error,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return _job(job)


@router.get("/jobs/{job_id}/map")
async def processing_map(job_id: uuid.UUID) -> dict[str, Any]:
    async with session_factory() as session:
        result = await session.scalar(
            select(ProcessingResult)
            .where(
                ProcessingResult.job_id == job_id,
                ProcessingResult.asset_name == "orthophoto.mbtiles",
            )
            .limit(1)
        )
        if result is None or not result.details:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No published orthophoto map for this job",
            )

        details = dict(result.details)
        if details.get("map_kind") != "RASTER_XYZ":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Processing result is not map-published",
            )

        return {
            "job_id": str(job_id),
            "result_id": str(result.id),
            "kind": "RASTER_XYZ",
            "tile_url": (
                f"/api/v1/processing/jobs/{job_id}/map/tiles/"
                "{z}/{x}/{y}"
            ),
            "bounds": details.get("bounds"),
            "minzoom": details.get("minzoom"),
            "maxzoom": details.get("maxzoom"),
            "tile_count": details.get("tile_count"),
            "attribution": details.get("attribution"),
        }


@router.get("/jobs/{job_id}/map/tiles/{z}/{x}/{y}")
async def processing_map_tile(
    job_id: uuid.UUID,
    z: int = Path(ge=0, le=30),
    x: int = Path(ge=0),
    y: int = Path(ge=0),
) -> StreamingResponse:
    async with session_factory() as session:
        result = await session.scalar(
            select(ProcessingResult)
            .where(
                ProcessingResult.job_id == job_id,
                ProcessingResult.asset_name == "orthophoto.mbtiles",
            )
            .limit(1)
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Orthophoto map not found",
            )

        details = result.details or {}
        prefix = details.get("tile_prefix")
        extension = details.get("tile_extension")
        content_type = details.get("tile_content_type")
        if not all(isinstance(value, str) and value for value in (prefix, extension, content_type)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Orthophoto tiles are not published",
            )

        bucket = result.bucket
        object_key = f"{prefix}/{z}/{x}/{y}.{extension}"

    client = create_storage_client()
    try:
        response = client.get_object(Bucket=bucket, Key=object_key)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tile not found",
        ) from exc

    body = response["Body"]

    def chunks():
        try:
            yield from body.iter_chunks(chunk_size=256 * 1024)
        finally:
            body.close()

    return StreamingResponse(
        chunks(),
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/jobs/{job_id}/scenes")
async def processing_scenes(job_id: uuid.UUID) -> list[dict[str, Any]]:
    async with session_factory() as session:
        results = (
            await session.scalars(
                select(ProcessingResult)
                .where(ProcessingResult.job_id == job_id)
                .order_by(ProcessingResult.asset_name)
            )
        ).all()

        scenes: list[dict[str, Any]] = []
        for result in results:
            details = result.details or {}
            if details.get("scene_kind") != "3D_TILES":
                continue
            tileset_path = details.get("tileset_path")
            if not isinstance(tileset_path, str) or not tileset_path:
                continue
            scenes.append(
                {
                    "job_id": str(job_id),
                    "result_id": str(result.id),
                    "asset_name": result.asset_name,
                    "scene_type": details.get("scene_type"),
                    "tileset_url": (
                        f"/api/v1/processing/jobs/{job_id}/scenes/"
                        f"{result.id}/{tileset_path}"
                    ),
                    "bounds": details.get("bounds"),
                    "file_count": details.get("file_count"),
                    "published_bytes": details.get("published_bytes"),
                    "asset_version": details.get("asset_version"),
                }
            )
        return scenes


@router.get("/jobs/{job_id}/scenes/{result_id}/{asset_path:path}")
async def processing_scene_asset(
    job_id: uuid.UUID,
    result_id: uuid.UUID,
    asset_path: str,
) -> StreamingResponse:
    normalized = asset_path.replace("\\", "/").strip("/")
    parts = normalized.split("/")
    if not normalized or ".." in parts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid scene asset path",
        )

    async with session_factory() as session:
        result = await session.get(ProcessingResult, result_id)
        if result is None or result.job_id != job_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="3D scene result not found",
            )

        details = result.details or {}
        prefix = details.get("scene_prefix")
        if details.get("scene_kind") != "3D_TILES" or not isinstance(prefix, str):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="3D scene is not published",
            )

        bucket = result.bucket
        object_key = f"{prefix}/{normalized}"

    client = create_storage_client()
    try:
        response = client.get_object(Bucket=bucket, Key=object_key)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="3D scene asset not found",
        ) from exc

    body = response["Body"]
    content_type = response.get("ContentType") or "application/octet-stream"

    def chunks():
        try:
            yield from body.iter_chunks(chunk_size=1024 * 1024)
        finally:
            body.close()

    return StreamingResponse(
        chunks(),
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/jobs/{job_id}/maps")
async def processing_maps(job_id: uuid.UUID) -> list[dict[str, Any]]:
    async with session_factory() as session:
        results = (
            await session.scalars(
                select(ProcessingResult)
                .where(ProcessingResult.job_id == job_id)
                .order_by(ProcessingResult.asset_name)
            )
        ).all()

        maps: list[dict[str, Any]] = []
        for result in results:
            details = result.details or {}
            if details.get("map_kind") != "RASTER_XYZ":
                continue

            layer_type = details.get("layer_type") or result.asset_name
            maps.append(
                {
                    "job_id": str(job_id),
                    "result_id": str(result.id),
                    "kind": "RASTER_XYZ",
                    "layer_type": layer_type,
                    "tile_url": (
                        f"/api/v1/processing/jobs/{job_id}/maps/{result.id}/tiles/"
                        "{z}/{x}/{y}"
                    ),
                    "bounds": details.get("bounds"),
                    "minzoom": details.get("minzoom"),
                    "maxzoom": details.get("maxzoom"),
                    "tile_count": details.get("tile_count"),
                    "attribution": details.get("attribution"),
                }
            )
        return maps


@router.get("/jobs/{job_id}/maps/{result_id}/tiles/{z}/{x}/{y}")
async def processing_result_map_tile(
    job_id: uuid.UUID,
    result_id: uuid.UUID,
    z: int = Path(ge=0, le=30),
    x: int = Path(ge=0),
    y: int = Path(ge=0),
) -> StreamingResponse:
    async with session_factory() as session:
        result = await session.get(ProcessingResult, result_id)
        if result is None or result.job_id != job_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Processing map result not found",
            )

        details = result.details or {}
        prefix = details.get("tile_prefix")
        extension = details.get("tile_extension")
        content_type = details.get("tile_content_type")
        if details.get("map_kind") != "RASTER_XYZ" or not all(
            isinstance(value, str) and value
            for value in (prefix, extension, content_type)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Processing map tiles are not published",
            )

        bucket = result.bucket
        object_key = f"{prefix}/{z}/{x}/{y}.{extension}"

    client = create_storage_client()
    try:
        response = client.get_object(Bucket=bucket, Key=object_key)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tile not found",
        ) from exc

    body = response["Body"]

    def chunks():
        try:
            yield from body.iter_chunks(chunk_size=256 * 1024)
        finally:
            body.close()

    return StreamingResponse(
        chunks(),
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
