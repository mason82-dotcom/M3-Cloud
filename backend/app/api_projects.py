from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.database import session_factory
from app.models import (
    Flight,
    MediaDatasetRecord,
    ProcessingJob,
    ProcessingResult,
    Project,
    Survey,
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
