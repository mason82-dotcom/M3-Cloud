from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from app.api_missions import (
    MissionCreate,
    MissionItemInput,
    MissionUpdate,
    create_mission,
    mission_revision,
    mission_revisions,
    update_mission,
)
from app.api_projects import ProjectCreate, SurveyCreate, create_project, create_survey
from app.database import session_factory
from app.missions.plans import compatibility, normalize_plan, plan_sha256
from app.models import Mission, Project, Survey


@pytest.mark.asyncio(loop_scope="session")
async def test_mission_plan_is_persistent_hashed_and_non_executable() -> None:
    async with session_factory() as session:
        await session.execute(delete(Mission))
        await session.execute(delete(Survey))
        await session.execute(delete(Project))
        await session.commit()

    project = await create_project(ProjectCreate(name="Mission project"))
    project_id = __import__("uuid").UUID(project["id"])
    survey = await create_survey(
        project_id,
        SurveyCreate(name="Mapping 01", kind="MAPPING"),
    )
    survey_id = __import__("uuid").UUID(survey["id"])

    created = await create_mission(
        MissionCreate(
            name="Grid A",
            survey_id=survey_id,
            aircraft_sn="M3E-001",
            preferred_executor="DJI_NATIVE",
            items=[
                MissionItemInput(
                    command=16,
                    latitude_deg=49.0,
                    longitude_deg=8.0,
                    altitude_m=60.0,
                ),
                MissionItemInput(
                    command=16,
                    latitude_deg=49.001,
                    longitude_deg=8.001,
                    altitude_m=60.0,
                ),
            ],
        )
    )

    assert created["status"] == "READY"
    assert created["item_count"] == 2
    assert created["compatibility"]["m3cloud_execution_enabled"] is False
    assert created["compatibility"]["lyrebird_mavlink_upload_compatible"] is True
    assert len(created["plan_sha256"]) == 64

    mission_id = __import__("uuid").UUID(created["id"])
    updated = await update_mission(
        mission_id,
        MissionUpdate(
            items=[
                MissionItemInput(
                    command=16,
                    latitude_deg=49.0,
                    longitude_deg=8.0,
                    altitude_m=70.0,
                )
            ]
        ),
    )
    assert updated["plan_version"] == 2
    assert updated["plan_sha256"] != created["plan_sha256"]

    revisions = await mission_revisions(mission_id)
    assert [revision["version"] for revision in revisions] == [1, 2]
    assert revisions[0]["plan_sha256"] == created["plan_sha256"]
    assert revisions[1]["plan_sha256"] == updated["plan_sha256"]
    assert revisions[0]["plan"]["items"][0]["altitude_m"] == 60.0
    assert revisions[1]["plan"]["items"][0]["altitude_m"] == 70.0

    first = await mission_revision(mission_id, 1)
    assert first["plan_sha256"] == created["plan_sha256"]

    async with session_factory() as session:
        stored = await session.get(Mission, mission_id)
        assert stored is not None
        assert stored.survey_id == survey_id
        assert stored.aircraft_sn == "M3E-001"
        assert stored.item_count == 1


def test_plan_validation_rejects_non_contiguous_sequence_and_reports_unsupported() -> None:
    with pytest.raises(ValueError):
        normalize_plan(
            [
                {
                    "seq": 1,
                    "command": 16,
                    "latitude_deg": 49.0,
                    "longitude_deg": 8.0,
                    "altitude_m": 50.0,
                }
            ]
        )

    plan = normalize_plan(
        [
            {
                "seq": 0,
                "command": 999999,
                "latitude_deg": 0.0,
                "longitude_deg": 0.0,
                "altitude_m": 0.0,
            }
        ]
    )
    info = compatibility(plan)
    assert info["m3cloud_execution_enabled"] is False
    assert info["lyrebird_mavlink_upload_compatible"] is False
    assert info["lyrebird_unsupported_items"] == [{"seq": 0, "command": 999999}]
    assert plan_sha256(plan) == plan_sha256(plan)


@pytest.mark.asyncio(loop_scope="session")
async def test_empty_mission_cannot_be_marked_ready() -> None:
    async with session_factory() as session:
        await session.execute(delete(Mission))
        await session.commit()

    created = await create_mission(MissionCreate(name="Empty"))
    mission_id = __import__("uuid").UUID(created["id"])

    with pytest.raises(HTTPException) as exc:
        await update_mission(mission_id, MissionUpdate(status="READY"))
    assert exc.value.status_code == 422
