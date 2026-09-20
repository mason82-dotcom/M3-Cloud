from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from app.api_projects import (
    ProjectCreate,
    SurveyAssignment,
    SurveyCreate,
    SurveyFromDatasetCreate,
    assign_dataset_survey,
    assign_flight_survey,
    create_project,
    create_survey,
    create_survey_from_dataset,
    survey_lineage,
)
from app.database import session_factory
from app.models import (
    Flight,
    MediaAsset,
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
        await session.execute(delete(MediaAsset))
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
        assets = [
            MediaAsset(
                relative_path=f"M3E/site-alpha/DJI_{index:04d}_W.JPG",
                filename=f"DJI_{index:04d}_W.JPG",
                extension=".jpg",
                size_bytes=100 + index,
                mtime_ns=index,
                sha256=(str(index) * 64)[:64],
                capture_time_utc=now,
                capture_time_source="TEST",
                metadata_version=1,
                metadata_status="READY",
                metadata_error=None,
                metadata_json={},
                platform="M3E",
                media_kind="WIDE",
                capture_group=f"M3E/site-alpha/DJI_{index:04d}",
                storage_mode="EXTERNAL",
                external_root="media-import",
                present=True,
                duplicate_of=None,
                discovered_at=now,
                last_seen_at=now,
            )
            for index in (1, 2)
        ]
        session.add_all([flight, dataset, *assets])
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

    manager = ProcessingManager(
        session_factory,
        media_root=str(tmp_path),
        webodm_enabled=True,
        webodm_url="http://webodm.invalid",
    )
    job = await manager.create_webodm_job(
        name="Survey ortho",
        input_prefix="M3E/site-alpha",
        platform="M3E",
        profile="m3e-ortho",
    )

    assert job.flight_id is None
    assert job.survey_id == survey_id

    lineage = await survey_lineage(survey_id)
    assert lineage["project"]["name"] == "Site Alpha"
    assert lineage["survey"]["name"] == "Survey 01"
    assert len(lineage["flights"]) == 1
    assert len(lineage["datasets"]) == 1
    assert len(lineage["processing_jobs"]) == 1
    assert lineage["processing_jobs"][0]["id"] == str(job.id)

    async with session_factory() as session:
        stored = await session.get(ProcessingJob, job.id)
        assert stored is not None
        assert stored.survey_id == survey_id



@pytest.mark.asyncio(loop_scope="session")
async def test_create_survey_from_dataset_infers_kind_and_links_flight() -> None:
    async with session_factory() as session:
        await session.execute(delete(ProcessingJob))
        await session.execute(delete(MediaDatasetRecord))
        await session.execute(delete(MediaAsset))
        await session.execute(delete(Flight))
        await session.execute(delete(Survey))
        await session.execute(delete(Project))
        await session.commit()

    project = await create_project(ProjectCreate(name="Thermal project"))
    project_id = __import__("uuid").UUID(project["id"])
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        flight = Flight(
            aircraft_sn="M3T-TEST",
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
        session.add(flight)
        await session.flush()

        dataset = MediaDatasetRecord(
            prefix="M3T/inspection-roof",
            platform="M3T",
            flight_id=flight.id,
            survey_id=None,
            title=None,
            capture_started_at=now,
            capture_ended_at=now,
            flight_assignment_source="AUTO",
            flight_match_status="MATCHED_TIME_GPS",
            flight_match_candidates=[str(flight.id)],
            flight_match_details={},
            present=True,
            created_at=now,
            updated_at=now,
        )
        session.add(dataset)
        await session.commit()
        await session.refresh(dataset)
        dataset_id = dataset.id
        flight_id = flight.id

    survey = await create_survey_from_dataset(
        project_id,
        dataset_id,
        SurveyFromDatasetCreate(),
    )

    assert survey["name"] == "inspection-roof"
    assert survey["kind"] == "THERMAL"
    assert survey["dataset_count"] == 1
    assert survey["flight_count"] == 1

    async with session_factory() as session:
        stored_dataset = await session.get(MediaDatasetRecord, dataset_id)
        stored_flight = await session.get(Flight, flight_id)
        assert stored_dataset is not None
        assert stored_flight is not None
        assert str(stored_dataset.survey_id) == survey["id"]
        assert str(stored_flight.survey_id) == survey["id"]



@pytest.mark.asyncio(loop_scope="session")
async def test_create_survey_from_dataset_rejects_cross_project_reuse() -> None:
    from fastapi import HTTPException

    async with session_factory() as session:
        await session.execute(delete(ProcessingJob))
        await session.execute(delete(MediaDatasetRecord))
        await session.execute(delete(MediaAsset))
        await session.execute(delete(Flight))
        await session.execute(delete(Survey))
        await session.execute(delete(Project))
        await session.commit()

    project_a = await create_project(ProjectCreate(name="Project A"))
    project_b = await create_project(ProjectCreate(name="Project B"))
    project_a_id = __import__("uuid").UUID(project_a["id"])
    project_b_id = __import__("uuid").UUID(project_b["id"])
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        dataset = MediaDatasetRecord(
            prefix="M3E/site-a",
            platform="M3E",
            flight_id=None,
            survey_id=None,
            title=None,
            capture_started_at=now,
            capture_ended_at=now,
            flight_assignment_source="AUTO",
            flight_match_status="NO_MATCH",
            flight_match_candidates=[],
            flight_match_details={},
            present=True,
            created_at=now,
            updated_at=now,
        )
        session.add(dataset)
        await session.commit()
        await session.refresh(dataset)
        dataset_id = dataset.id

    survey = await create_survey_from_dataset(
        project_a_id,
        dataset_id,
        SurveyFromDatasetCreate(),
    )
    assert survey["project_id"] == str(project_a_id)

    with pytest.raises(HTTPException) as exc:
        await create_survey_from_dataset(
            project_b_id,
            dataset_id,
            SurveyFromDatasetCreate(),
        )
    assert exc.value.status_code == 409
