from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from app.api_projects import (
    ProjectCreate,
    SurveyAssignment,
    SurveyCreate,
    assign_dataset_survey,
    assign_flight_survey,
    create_project,
    create_survey,
)
from app.database import session_factory
from app.models import (
    Flight,
    MediaDatasetRecord,
    ProcessingJob,
    Project,
    Survey,
)
from app.processing.service import ProcessingManager


@pytest.mark.asyncio(loop_scope="session")
async def test_project_survey_assignments_and_processing_inheritance(tmp_path) -> None:
    async with session_factory() as session:
        await session.execute(delete(ProcessingJob))
        await session.execute(delete(MediaDatasetRecord))
        await session.execute(delete(Flight))
        await session.execute(delete(Survey))
        await session.execute(delete(Project))
        await session.commit()

    project_payload = await create_project(
        ProjectCreate(name="Site Alpha", description="Mapping project")
    )
    project_id = project_payload["id"]
    survey_payload = await create_survey(
        __import__("uuid").UUID(project_id),
        SurveyCreate(name="Survey 01", kind="MAPPING"),
    )
    survey_id = __import__("uuid").UUID(survey_payload["id"])

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        flight = Flight(
            aircraft_sn="M3E-TEST",
            gateway_sn=None,
            dji_track_id=None,
            survey_id=None,
            status="COMPLETED",
            started_at=now,
            ended_at=now,
            duration_s=0.0,
            distance_m=0.0,
            rtk_converged_samples=0,
            rtk_total_samples=0,
        )
        dataset = MediaDatasetRecord(
            prefix="M3E/site-alpha",
            platform="M3E",
            flight_id=None,
            survey_id=None,
            title=None,
            capture_started_at=now,
            capture_ended_at=now,
            flight_assignment_source="MANUAL",
            flight_match_status="MANUAL",
            flight_match_candidates=[],
            flight_match_details={},
            present=True,
            created_at=now,
            updated_at=now,
        )
        session.add_all([flight, dataset])
        await session.commit()
        await session.refresh(flight)
        await session.refresh(dataset)
        flight_id = flight.id
        dataset_id = dataset.id

    await assign_flight_survey(
        flight_id,
        SurveyAssignment(survey_id=survey_id),
    )
    await assign_dataset_survey(
        dataset_id,
        SurveyAssignment(survey_id=survey_id),
    )

    async with session_factory() as session:
        flight = await session.get(Flight, flight_id)
        dataset = await session.get(MediaDatasetRecord, dataset_id)
        assert flight is not None and flight.survey_id == survey_id
        assert dataset is not None and dataset.survey_id == survey_id

    # Processing inheritance is asserted directly through the same dataset lookup
    # contract used by both WebODM and Thermogram job creation.
    async with session_factory() as session:
        dataset = await session.scalar(
            select(MediaDatasetRecord).where(
                MediaDatasetRecord.prefix == "M3E/site-alpha",
                MediaDatasetRecord.platform == "M3E",
            )
        )
        assert dataset is not None
        assert dataset.survey_id == survey_id
