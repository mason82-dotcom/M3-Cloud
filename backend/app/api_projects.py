from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.database import session_factory
from app.media.datasets import dataset_prefix
from app.media.metadata import asset_metadata_payload
from app.models import (
    Flight,
    MediaAsset,
    MediaDatasetRecord,
    Mission,
    ProcessingJob,
    ProcessingJobAsset,
    ProcessingResult,
    Project,
    Survey,
    TelemetrySample,
)


router = APIRouter(prefix="/api/v1", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["ACTIVE", "ARCHIVED"] | None = None


class SurveyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: Literal[
        "GENERIC",
        "MAPPING",
        "THERMAL",
        "MULTISPECTRAL",
        "INSPECTION",
    ] = "GENERIC"
    description: str | None = Field(default=None, max_length=4000)


class SurveyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    kind: Literal[
        "GENERIC",
        "MAPPING",
        "THERMAL",
        "MULTISPECTRAL",
        "INSPECTION",
    ] | None = None
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["ACTIVE", "COMPLETED", "ARCHIVED"] | None = None


class SurveyAssignment(BaseModel):
    survey_id: uuid.UUID | None


class SurveyFromDatasetCreate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


def _project(project: Project, survey_count: int = 0) -> dict[str, Any]:
    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "survey_count": survey_count,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


async def _survey_payload(session, survey: Survey) -> dict[str, Any]:
    flight_count = int(
        await session.scalar(
            select(func.count(Flight.id)).where(Flight.survey_id == survey.id)
        )
        or 0
    )
    dataset_count = int(
        await session.scalar(
            select(func.count(MediaDatasetRecord.id)).where(
                MediaDatasetRecord.survey_id == survey.id
            )
        )
        or 0
    )
    mission_count = int(
        await session.scalar(
            select(func.count(Mission.id)).where(Mission.survey_id == survey.id)
        )
        or 0
    )
    processing_count = int(
        await session.scalar(
            select(func.count(ProcessingJob.id)).where(
                ProcessingJob.survey_id == survey.id
            )
        )
        or 0
    )
    return {
        "id": str(survey.id),
        "project_id": str(survey.project_id),
        "name": survey.name,
        "kind": survey.kind,
        "description": survey.description,
        "status": survey.status,
        "flight_count": flight_count,
        "dataset_count": dataset_count,
        "mission_count": mission_count,
        "processing_count": processing_count,
        "created_at": survey.created_at.isoformat(),
        "updated_at": survey.updated_at.isoformat(),
    }


@router.get("/projects")
async def list_projects() -> list[dict[str, Any]]:
    async with session_factory() as session:
        projects = (
            await session.scalars(
                select(Project).order_by(Project.updated_at.desc(), Project.name)
            )
        ).all()
        counts = {
            project_id: int(count)
            for project_id, count in (
                await session.execute(
                    select(Survey.project_id, func.count(Survey.id)).group_by(
                        Survey.project_id
                    )
                )
            ).all()
        }
        return [_project(project, counts.get(project.id, 0)) for project in projects]


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    project = Project(
        name=body.name.strip(),
        description=body.description,
        status="ACTIVE",
        created_at=now,
        updated_at=now,
    )
    async with session_factory() as session:
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return _project(project)


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
) -> dict[str, Any]:
    async with session_factory() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        values = body.model_dump(exclude_unset=True)
        if "name" in values and values["name"] is not None:
            project.name = values["name"].strip()
        if "description" in values:
            project.description = values["description"]
        if "status" in values and values["status"] is not None:
            project.status = values["status"]
        project.updated_at = datetime.now(timezone.utc)
        await session.commit()

        survey_count = int(
            await session.scalar(
                select(func.count(Survey.id)).where(Survey.project_id == project.id)
            )
            or 0
        )
        return _project(project, survey_count)


@router.get("/projects/{project_id}/surveys")
async def list_project_surveys(project_id: uuid.UUID) -> list[dict[str, Any]]:
    async with session_factory() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        surveys = (
            await session.scalars(
                select(Survey)
                .where(Survey.project_id == project_id)
                .order_by(Survey.updated_at.desc(), Survey.name)
            )
        ).all()
        return [await _survey_payload(session, survey) for survey in surveys]


@router.post(
    "/projects/{project_id}/surveys",
    status_code=status.HTTP_201_CREATED,
)
async def create_survey(
    project_id: uuid.UUID,
    body: SurveyCreate,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        existing = await session.scalar(
            select(Survey).where(
                Survey.project_id == project_id,
                Survey.name == body.name.strip(),
            )
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Survey name already exists in project",
            )

        survey = Survey(
            project_id=project_id,
            name=body.name.strip(),
            kind=body.kind,
            description=body.description,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        session.add(survey)
        project.updated_at = now
        await session.commit()
        await session.refresh(survey)
        return await _survey_payload(session, survey)


@router.patch("/surveys/{survey_id}")
async def update_survey(
    survey_id: uuid.UUID,
    body: SurveyUpdate,
) -> dict[str, Any]:
    async with session_factory() as session:
        survey = await session.get(Survey, survey_id)
        if survey is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Survey not found",
            )
        values = body.model_dump(exclude_unset=True)
        for key in ("name", "kind", "description", "status"):
            if key in values:
                value = values[key]
                if key == "name" and value is not None:
                    value = value.strip()
                setattr(survey, key, value)
        survey.updated_at = datetime.now(timezone.utc)
        project = await session.get(Project, survey.project_id)
        if project is not None:
            project.updated_at = survey.updated_at
        await session.commit()
        return await _survey_payload(session, survey)


async def _resolve_survey(session, survey_id: uuid.UUID | None) -> Survey | None:
    if survey_id is None:
        return None
    survey = await session.get(Survey, survey_id)
    if survey is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Survey not found",
        )
    return survey


@router.put("/flights/{flight_id}/survey")
async def assign_flight_survey(
    flight_id: uuid.UUID,
    body: SurveyAssignment,
) -> dict[str, Any]:
    async with session_factory() as session:
        flight = await session.get(Flight, flight_id)
        if flight is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Flight not found",
            )
        survey = await _resolve_survey(session, body.survey_id)
        flight.survey_id = survey.id if survey else None
        if survey:
            now = datetime.now(timezone.utc)
            survey.updated_at = now
            await session.execute(
                update(MediaDatasetRecord)
                .where(
                    MediaDatasetRecord.flight_id == flight.id,
                    MediaDatasetRecord.survey_id.is_(None),
                )
                .values(survey_id=survey.id, updated_at=now)
            )
            await session.execute(
                update(ProcessingJob)
                .where(
                    ProcessingJob.flight_id == flight.id,
                    ProcessingJob.survey_id.is_(None),
                )
                .values(survey_id=survey.id, updated_at=now)
            )
        await session.commit()
        return {
            "flight_id": str(flight.id),
            "survey_id": str(flight.survey_id) if flight.survey_id else None,
        }


@router.put("/media/datasets/{dataset_id}/survey")
async def assign_dataset_survey(
    dataset_id: uuid.UUID,
    body: SurveyAssignment,
) -> dict[str, Any]:
    async with session_factory() as session:
        dataset = await session.get(MediaDatasetRecord, dataset_id)
        if dataset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Media dataset not found",
            )
        survey = await _resolve_survey(session, body.survey_id)
        dataset.survey_id = survey.id if survey else None
        dataset.updated_at = datetime.now(timezone.utc)
        if survey:
            survey.updated_at = dataset.updated_at
            await session.execute(
                update(ProcessingJob)
                .where(
                    ProcessingJob.input_prefix == dataset.prefix,
                    ProcessingJob.platform == dataset.platform,
                    ProcessingJob.survey_id.is_(None),
                )
                .values(
                    survey_id=survey.id,
                    updated_at=dataset.updated_at,
                )
            )
        await session.commit()
        return {
            "dataset_id": str(dataset.id),
            "survey_id": str(dataset.survey_id) if dataset.survey_id else None,
        }


@router.get("/surveys/{survey_id}/lineage")
async def survey_lineage(survey_id: uuid.UUID) -> dict[str, Any]:
    async with session_factory() as session:
        survey = await session.get(Survey, survey_id)
        if survey is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Survey not found",
            )
        project = await session.get(Project, survey.project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        flights = (
            await session.scalars(
                select(Flight)
                .where(Flight.survey_id == survey_id)
                .order_by(Flight.started_at)
            )
        ).all()
        datasets = (
            await session.scalars(
                select(MediaDatasetRecord)
                .where(MediaDatasetRecord.survey_id == survey_id)
                .order_by(MediaDatasetRecord.prefix)
            )
        ).all()
        missions = (
            await session.scalars(
                select(Mission)
                .where(Mission.survey_id == survey_id)
                .order_by(Mission.updated_at.desc(), Mission.name)
            )
        ).all()
        jobs = (
            await session.scalars(
                select(ProcessingJob)
                .where(ProcessingJob.survey_id == survey_id)
                .order_by(ProcessingJob.created_at)
            )
        ).all()

        job_ids = [job.id for job in jobs]
        results = (
            await session.scalars(
                select(ProcessingResult)
                .where(ProcessingResult.job_id.in_(job_ids))
                .order_by(ProcessingResult.created_at, ProcessingResult.asset_name)
            )
        ).all() if job_ids else []

        results_by_job: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for result in results:
            results_by_job.setdefault(result.job_id, []).append(
                {
                    "id": str(result.id),
                    "asset_name": result.asset_name,
                    "content_type": result.content_type,
                    "size_bytes": result.size_bytes,
                    "sha256": result.sha256,
                    "details": result.details or {},
                    "created_at": result.created_at.isoformat(),
                }
            )

        return {
            "project": _project(
                project,
                int(
                    await session.scalar(
                        select(func.count(Survey.id)).where(
                            Survey.project_id == project.id
                        )
                    )
                    or 0
                ),
            ),
            "survey": await _survey_payload(session, survey),
            "flights": [
                {
                    "id": str(flight.id),
                    "aircraft_sn": flight.aircraft_sn,
                    "status": flight.status,
                    "started_at": flight.started_at.isoformat(),
                    "ended_at": flight.ended_at.isoformat() if flight.ended_at else None,
                    "distance_m": flight.distance_m,
                    "duration_s": flight.duration_s,
                }
                for flight in flights
            ],
            "missions": [
                {
                    "id": str(mission.id),
                    "name": mission.name,
                    "status": mission.status,
                    "source": mission.source,
                    "aircraft_sn": mission.aircraft_sn,
                    "preferred_executor": mission.preferred_executor,
                    "item_count": mission.item_count,
                    "plan_version": mission.plan_version,
                    "plan_sha256": mission.plan_sha256,
                    "updated_at": mission.updated_at.isoformat(),
                }
                for mission in missions
            ],
            "datasets": [
                {
                    "id": str(dataset.id),
                    "platform": dataset.platform,
                    "prefix": dataset.prefix,
                    "flight_id": str(dataset.flight_id) if dataset.flight_id else None,
                    "present": dataset.present,
                    "flight_match_status": dataset.flight_match_status,
                    "capture_started_at": (
                        dataset.capture_started_at.isoformat()
                        if dataset.capture_started_at
                        else None
                    ),
                    "capture_ended_at": (
                        dataset.capture_ended_at.isoformat()
                        if dataset.capture_ended_at
                        else None
                    ),
                }
                for dataset in datasets
            ],
            "processing_jobs": [
                {
                    "id": str(job.id),
                    "kind": job.kind,
                    "status": job.status,
                    "name": job.name,
                    "platform": job.platform,
                    "input_prefix": job.input_prefix,
                    "flight_id": str(job.flight_id) if job.flight_id else None,
                    "created_at": job.created_at.isoformat(),
                    "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                    "results": results_by_job.get(job.id, []),
                }
                for job in jobs
            ],
        }


def _survey_kind_for_platform(platform: str) -> str:
    return {
        "M3E": "MAPPING",
        "M3T": "THERMAL",
        "M3M": "MULTISPECTRAL",
    }.get(platform.upper(), "GENERIC")


@router.post(
    "/projects/{project_id}/surveys/from-dataset/{dataset_id}",
    status_code=status.HTTP_201_CREATED,
)
async def create_survey_from_dataset(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    body: SurveyFromDatasetCreate | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        dataset = await session.get(MediaDatasetRecord, dataset_id)
        if dataset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Media dataset not found",
            )
        if dataset.survey_id is not None:
            existing = await session.get(Survey, dataset.survey_id)
            if existing is not None:
                if existing.project_id != project_id:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Media dataset already belongs to a survey in another project",
                    )
                return await _survey_payload(session, existing)

        requested_name = body.name.strip() if body and body.name else ""
        default_name = PurePosixPath(dataset.prefix).name or dataset.platform
        name = requested_name or dataset.title or default_name

        collision = await session.scalar(
            select(Survey).where(
                Survey.project_id == project_id,
                Survey.name == name,
            )
        )
        if collision is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Survey name already exists in project",
            )

        survey = Survey(
            project_id=project_id,
            name=name,
            kind=_survey_kind_for_platform(dataset.platform),
            description=body.description if body else None,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        session.add(survey)
        await session.flush()

        dataset.survey_id = survey.id
        dataset.updated_at = now

        if dataset.flight_id is not None:
            flight = await session.get(Flight, dataset.flight_id)
            if flight is not None and flight.survey_id is None:
                flight.survey_id = survey.id

        await session.execute(
            update(ProcessingJob)
            .where(
                ProcessingJob.input_prefix == dataset.prefix,
                ProcessingJob.platform == dataset.platform,
                ProcessingJob.survey_id.is_(None),
            )
            .values(survey_id=survey.id, updated_at=now)
        )

        project.updated_at = now
        await session.commit()
        await session.refresh(survey)
        return await _survey_payload(session, survey)


async def _survey_manifest_payload(
    session,
    survey: Survey,
) -> dict[str, Any]:
    project = await session.get(Project, survey.project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    flights = (
        await session.scalars(
            select(Flight)
            .where(Flight.survey_id == survey.id)
            .order_by(Flight.started_at, Flight.id)
        )
    ).all()
    datasets = (
        await session.scalars(
            select(MediaDatasetRecord)
            .where(MediaDatasetRecord.survey_id == survey.id)
            .order_by(MediaDatasetRecord.platform, MediaDatasetRecord.prefix)
        )
    ).all()
    missions = (
        await session.scalars(
            select(Mission)
            .where(Mission.survey_id == survey.id)
            .order_by(Mission.updated_at, Mission.id)
        )
    ).all()
    jobs = (
        await session.scalars(
            select(ProcessingJob)
            .where(ProcessingJob.survey_id == survey.id)
            .order_by(ProcessingJob.created_at, ProcessingJob.id)
        )
    ).all()

    flight_items: list[dict[str, Any]] = []
    for flight in flights:
        source_rows = (
            await session.execute(
                select(TelemetrySample.source, func.count(TelemetrySample.id))
                .where(TelemetrySample.flight_id == flight.id)
                .group_by(TelemetrySample.source)
                .order_by(TelemetrySample.source)
            )
        ).all()
        flight_items.append(
            {
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
                "rtk_converged_samples": flight.rtk_converged_samples,
                "rtk_total_samples": flight.rtk_total_samples,
                "end_reason": flight.end_reason,
                "telemetry_sources": {
                    source: int(count)
                    for source, count in source_rows
                },
            }
        )

    dataset_items: list[dict[str, Any]] = []
    for dataset in datasets:
        assets = (
            await session.scalars(
                select(MediaAsset)
                .where(
                    MediaAsset.platform == dataset.platform,
                    MediaAsset.present.is_(True),
                    MediaAsset.duplicate_of.is_(None),
                )
                .order_by(MediaAsset.relative_path)
            )
        ).all()
        assets = [
            asset
            for asset in assets
            if dataset_prefix(asset.relative_path) == dataset.prefix
        ]

        dataset_items.append(
            {
                "id": str(dataset.id),
                "platform": dataset.platform,
                "prefix": dataset.prefix,
                "title": dataset.title,
                "flight_id": str(dataset.flight_id) if dataset.flight_id else None,
                "capture_started_at": (
                    dataset.capture_started_at.isoformat()
                    if dataset.capture_started_at
                    else None
                ),
                "capture_ended_at": (
                    dataset.capture_ended_at.isoformat()
                    if dataset.capture_ended_at
                    else None
                ),
                "flight_assignment_source": dataset.flight_assignment_source,
                "flight_match_status": dataset.flight_match_status,
                "flight_match_candidates": dataset.flight_match_candidates,
                "flight_match_details": dataset.flight_match_details,
                "present": dataset.present,
                "assets": [
                    {
                        "id": str(asset.id),
                        "relative_path": asset.relative_path,
                        "filename": asset.filename,
                        "media_kind": asset.media_kind,
                        "capture_group": asset.capture_group,
                        "size_bytes": asset.size_bytes,
                        "sha256": asset.sha256,
                        "capture_time_utc": (
                            asset.capture_time_utc.isoformat()
                            if asset.capture_time_utc
                            else None
                        ),
                        "metadata": asset_metadata_payload(asset),
                    }
                    for asset in assets
                ],
            }
        )

    job_items: list[dict[str, Any]] = []
    for job in jobs:
        frozen = (
            await session.scalars(
                select(ProcessingJobAsset)
                .where(ProcessingJobAsset.job_id == job.id)
                .order_by(ProcessingJobAsset.ordinal)
            )
        ).all()
        results = (
            await session.scalars(
                select(ProcessingResult)
                .where(ProcessingResult.job_id == job.id)
                .order_by(ProcessingResult.asset_name)
            )
        ).all()

        job_items.append(
            {
                "id": str(job.id),
                "kind": job.kind,
                "status": job.status,
                "name": job.name,
                "input_prefix": job.input_prefix,
                "platform": job.platform,
                "flight_id": str(job.flight_id) if job.flight_id else None,
                "media_kinds": job.media_kinds,
                "options": job.options,
                "remote_project_id": job.remote_project_id,
                "remote_task_id": job.remote_task_id,
                "created_at": job.created_at.isoformat(),
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                "inputs": [
                    {
                        "ordinal": item.ordinal,
                        "media_asset_id": str(item.media_asset_id),
                        "relative_path": item.relative_path,
                        "size_bytes": item.size_bytes,
                        "sha256": item.sha256,
                        "media_kind": item.media_kind,
                        "capture_group": item.capture_group,
                        "capture_time_utc": (
                            item.capture_time_utc.isoformat()
                            if item.capture_time_utc
                            else None
                        ),
                        "metadata": item.metadata_snapshot or {},
                    }
                    for item in frozen
                ],
                "results": [
                    {
                        "id": str(result.id),
                        "asset_name": result.asset_name,
                        "bucket": result.bucket,
                        "object_key": result.object_key,
                        "size_bytes": result.size_bytes,
                        "sha256": result.sha256,
                        "content_type": result.content_type,
                        "details": result.details or {},
                        "created_at": result.created_at.isoformat(),
                    }
                    for result in results
                ],
            }
        )

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": _project(
            project,
            int(
                await session.scalar(
                    select(func.count(Survey.id)).where(
                        Survey.project_id == project.id
                    )
                )
                or 0
            ),
        ),
        "survey": await _survey_payload(session, survey),
        "flights": flight_items,
        "missions": [
            {
                "id": str(mission.id),
                "name": mission.name,
                "kind": mission.kind,
                "source": mission.source,
                "status": mission.status,
                "aircraft_sn": mission.aircraft_sn,
                "preferred_executor": mission.preferred_executor,
                "external_ref": mission.external_ref,
                "plan_version": mission.plan_version,
                "item_count": mission.item_count,
                "plan_sha256": mission.plan_sha256,
                "plan": mission.plan_json,
                "created_at": mission.created_at.isoformat(),
                "updated_at": mission.updated_at.isoformat(),
            }
            for mission in missions
        ],
        "datasets": dataset_items,
        "processing_jobs": job_items,
    }


@router.get("/surveys/{survey_id}/manifest")
async def survey_manifest(survey_id: uuid.UUID) -> dict[str, Any]:
    async with session_factory() as session:
        survey = await session.get(Survey, survey_id)
        if survey is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Survey not found",
            )
        return await _survey_manifest_payload(session, survey)


@router.get("/surveys/{survey_id}/manifest/download")
async def download_survey_manifest(survey_id: uuid.UUID) -> Response:
    manifest = await survey_manifest(survey_id)
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
            "Content-Disposition": 'attachment; filename="m3-survey-manifest.json"',
            "Content-Length": str(len(payload)),
        },
    )
