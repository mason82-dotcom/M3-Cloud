from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.database import session_factory
from app.models import ProcessingJob
from app.processing.profiles import DEFAULT_PROFILE, profile_catalog


router = APIRouter(prefix="/api/v1/processing", tags=["processing"])


class WebODMJobRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    input_prefix: str = Field(min_length=1, max_length=1024)
    platform: str | None = None
    profile: str = DEFAULT_PROFILE


def _job(job: ProcessingJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "kind": job.kind,
        "status": job.status,
        "name": job.name,
        "input_prefix": job.input_prefix,
        "platform": job.platform,
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
