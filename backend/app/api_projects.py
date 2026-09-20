from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.database import session_factory
from app.models import Flight, MediaDatasetRecord, ProcessingJob, Project, Survey


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
            survey.updated_at = datetime.now(timezone.utc)
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
        await session.commit()
        return {
            "dataset_id": str(dataset.id),
            "survey_id": str(dataset.survey_id) if dataset.survey_id else None,
        }
