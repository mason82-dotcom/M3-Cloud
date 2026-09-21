from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pymavlink.dialects.v20 import common as mavlink_common
from sqlalchemy import delete

from app.api_missions import (
    create_mission_deployment,
    upload_mission_deployment,
    mission_deployments,
    mission_detail,
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
from app.missions.deployment import deployment_sha256
from app.missions.uploader import (
    MissionUploadError,
    MissionUploadResult,
    recover_interrupted_uploads,
)
from app.missions.plans import (
    compatibility,
    compile_mission_item_int,
    mission_runtime_id,
    normalize_plan,
    plan_sha256,
)
from app.vehicles.base import VehicleSnapshot
from app.models import Mission, MissionDeployment, Project, Survey


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
    assert created["compatibility"]["wire_ready"] is True
    assert created["compatibility"]["lyrebird_mavlink_upload_compatible"] is True
    assert created["plan"]["schema_version"] == 2
    assert created["plan"]["items"][0]["frame"] == 6
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


def test_mission_runtime_id_matches_lyrebird_golden_vector() -> None:
    plan = normalize_plan(
        [
            {
                "seq": 0,
                "frame": 6,
                "command": 16,
                "param1": 0.0,
                "param2": 0.0,
                "param3": 0.0,
                "param4": None,
                "latitude_deg": 46.518,
                "longitude_deg": 6.566,
                "altitude_m": 30.0,
                "autocontinue": True,
            }
        ]
    )
    wire = compile_mission_item_int(plan)
    assert mission_runtime_id(wire) == 0xD495F750


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
    assert info["lyrebird_unsupported_frames"] == []
    assert plan_sha256(plan) == plan_sha256(plan)

    unsupported_frame = normalize_plan(
        [
            {
                "seq": 0,
                "frame": 0,
                "command": 16,
                "latitude_deg": 49.0,
                "longitude_deg": 8.0,
                "altitude_m": 50.0,
            }
        ]
    )
    frame_info = compatibility(unsupported_frame)
    assert frame_info["wire_ready"] is False
    assert frame_info["lyrebird_unsupported_frames"] == [{"seq": 0, "frame": 0}]

    positional_frame3 = normalize_plan(
        [
            {
                "seq": 0,
                "frame": 3,
                "command": 16,
                "latitude_deg": 49.0,
                "longitude_deg": 8.0,
                "altitude_m": 50.0,
            }
        ]
    )
    frame3_info = compatibility(positional_frame3)
    assert frame3_info["wire_ready"] is False
    assert frame3_info["lyrebird_unsupported_frames"] == [{"seq": 0, "frame": 3}]

    nonpositional_mission_frame = normalize_plan(
        [
            {
                "seq": 0,
                "frame": 2,
                "command": mavlink_common.MAV_CMD_DO_CHANGE_SPEED,
                "param2": 8.0,
                "latitude_deg": 0.0,
                "longitude_deg": 0.0,
                "altitude_m": 0.0,
            }
        ]
    )
    assert compatibility(nonpositional_mission_frame)["wire_ready"] is True

    wire_plan = normalize_plan(
        [
            {
                "seq": 0,
                "frame": 6,
                "command": 16,
                "param4": None,
                "latitude_deg": 49.1234567,
                "longitude_deg": 8.7654321,
                "altitude_m": 50.5,
                "autocontinue": False,
            }
        ]
    )
    wire = compile_mission_item_int(wire_plan)
    assert wire["target_system"] == "RUNTIME"
    assert wire["null_float_encoding"] == "IEEE754_NAN"
    assert wire["items"][0]["x"] == 491234567
    assert wire["items"][0]["y"] == 87654321
    assert wire["items"][0]["z"] == 50.5
    assert wire["items"][0]["param4"] is None
    assert wire["items"][0]["autocontinue"] == 0
    assert mission_runtime_id(wire) == mission_runtime_id(wire)
    assert mission_runtime_id(wire) != 0


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



class _DeploymentRegistry:
    def __init__(self, vehicle):
        self.vehicle = vehicle

    async def list_vehicles(self):
        return [self.vehicle]


@pytest.mark.asyncio(loop_scope="session")
async def test_ready_mission_seals_immutable_non_executing_handoff(monkeypatch) -> None:
    async with session_factory() as session:
        await session.execute(delete(MissionDeployment))
        await session.execute(delete(Mission))
        await session.commit()

    created = await create_mission(
        MissionCreate(
            name="Deployable",
            aircraft_sn="M3E-HANDOFF",
            preferred_executor="DJI_NATIVE",
            items=[
                MissionItemInput(
                    command=16,
                    latitude_deg=49.0,
                    longitude_deg=8.0,
                    altitude_m=50.0,
                )
            ],
        )
    )
    mission_id = __import__("uuid").UUID(created["id"])

    vehicle = VehicleSnapshot(
        id="vehicle:M3E-HANDOFF",
        sn="M3E-HANDOFF",
        name="M3E",
        model="M3E",
        source="lyrebird",
        online=True,
        sources=("lyrebird",),
        telemetry={
            "aircraft_state": {
                "failsafe": False,
                "positioning": {
                    "fix": "FIXED",
                    "rtk": {"fix": "FIXED"},
                },
            },
            "safety": {
                "ready_to_takeoff": True,
                "manual_override": False,
            },
            "battery": {"capacity_percent": 80},
        },
    )
    monkeypatch.setattr(
        "app.api_missions._registry",
        lambda request: _DeploymentRegistry(vehicle),
    )

    sealed = await create_mission_deployment(mission_id, object())
    assert sealed["revision_version"] == 1
    assert sealed["plan_sha256"] == created["plan_sha256"]
    assert sealed["aircraft_sn"] == "M3E-HANDOFF"
    assert sealed["package"]["preflight"]["checks_passed"] is True
    assert sealed["package"]["handoff"]["upload_enabled"] is True
    assert sealed["package"]["handoff"]["execution_enabled"] is False
    assert sealed["upload_status"] == "SEALED"
    assert sealed["upload_attempts"] == 0
    assert sealed["package"]["handoff"]["wire_ready"] is True
    assert sealed["package"]["handoff"]["frame_policy"] == "EXPLICIT_PER_ITEM"
    assert sealed["package"]["wire"]["message"] == "MISSION_ITEM_INT"
    assert sealed["package"]["wire"]["target_system"] == "RUNTIME"
    assert sealed["package"]["wire"]["items"][0]["frame"] == 6
    assert sealed["package"]["wire"]["items"][0]["x"] == 490000000
    assert sealed["package"]["wire"]["mission_id"] != 0
    assert sealed["package_sha256"] == deployment_sha256(sealed["package"])

    listed = await mission_deployments(mission_id)
    assert len(listed) == 1
    assert listed[0]["id"] == sealed["id"]

    # Later mission edits create a new revision but do not mutate the sealed package.
    await update_mission(
        mission_id,
        MissionUpdate(
            items=[
                MissionItemInput(
                    command=16,
                    latitude_deg=49.0,
                    longitude_deg=8.0,
                    altitude_m=80.0,
                )
            ]
        ),
    )
    listed_after = await mission_deployments(mission_id)
    assert listed_after[0]["revision_version"] == 1
    assert listed_after[0]["package"]["revision"]["plan"]["items"][0]["altitude_m"] == 50.0


    runtime_id = sealed["package"]["wire"]["mission_id"]
    runtime_vehicle = VehicleSnapshot(
        id="vehicle:M3E-HANDOFF",
        sn="M3E-HANDOFF",
        name="M3E",
        model="M3E",
        source="lyrebird",
        online=True,
        sources=("lyrebird",),
        telemetry={
            "mission": {
                "state": 2,
                "current_seq": 0,
                "mission_id": runtime_id,
            }
        },
    )
    monkeypatch.setattr(
        "app.api_missions._registry",
        lambda request: _DeploymentRegistry(runtime_vehicle),
    )

    observed = await mission_detail(mission_id, object())
    assert observed["runtime"]["runtime_plan_identity"] == "VERIFIED"
    assert observed["runtime"]["linked_to_persisted_plan"] is True
    assert observed["runtime"]["deployment_id"] == sealed["id"]
    assert observed["runtime"]["revision_version"] == 1
    assert observed["runtime"]["plan_sha256"] == created["plan_sha256"]



class _ApiUploader:
    def __init__(self, *, error: MissionUploadError | None = None):
        self.error = error
        self.calls = []

    async def upload(self, package, *, aircraft_sn, preferred_executor):
        self.calls.append(
            {
                "package": package,
                "aircraft_sn": aircraft_sn,
                "preferred_executor": preferred_executor,
            }
        )
        if self.error is not None:
            raise self.error
        runtime_id = int(package["wire"]["mission_id"])
        return MissionUploadResult(
            host="10.0.0.2",
            system_id=123,
            executor="dji_native",
            item_count=len(package["wire"]["items"]),
            requested_sequences=tuple(
                item["seq"] for item in package["wire"]["items"]
            ),
            ack_result=0,
            runtime_mission_id=runtime_id,
            readback_verified=True,
            readback_item_count=len(package["wire"]["items"]),
            readback_runtime_mission_id=runtime_id,
        )


def _request_with_uploader(uploader):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(mission_uploader=uploader)
        )
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_mission_upload_endpoint_persists_success_and_failure(monkeypatch) -> None:
    async with session_factory() as session:
        await session.execute(delete(MissionDeployment))
        await session.execute(delete(Mission))
        await session.commit()

    vehicle = VehicleSnapshot(
        id="vehicle:M3E-UPLOAD",
        sn="M3E-UPLOAD",
        name="M3E",
        model="M3E",
        source="lyrebird",
        online=True,
        sources=("lyrebird",),
        telemetry={
            "mission": {"state": 2, "current_seq": 0, "mission_id": 0},
            "aircraft_state": {
                "failsafe": False,
                "positioning": {
                    "fix": "FIXED",
                    "rtk": {"fix": "FIXED"},
                },
            },
            "safety": {
                "ready_to_takeoff": True,
                "manual_override": False,
            },
            "battery": {"capacity_percent": 80},
        },
    )
    monkeypatch.setattr(
        "app.api_missions._registry",
        lambda request: _DeploymentRegistry(vehicle),
    )
    monkeypatch.setattr(
        "app.api_missions.settings.mission_upload_enabled",
        True,
    )

    created = await create_mission(
        MissionCreate(
            name="Upload endpoint",
            aircraft_sn="M3E-UPLOAD",
            preferred_executor="DJI_NATIVE",
            items=[
                MissionItemInput(
                    command=16,
                    latitude_deg=49.0,
                    longitude_deg=8.0,
                    altitude_m=50.0,
                )
            ],
        )
    )
    mission_id = __import__("uuid").UUID(created["id"])
    sealed = await create_mission_deployment(mission_id, object())
    deployment_id = __import__("uuid").UUID(sealed["id"])

    uploader = _ApiUploader()
    uploaded = await upload_mission_deployment(
        mission_id,
        deployment_id,
        _request_with_uploader(uploader),
    )

    assert uploaded["upload_status"] == "UPLOADED"
    assert uploaded["upload_attempts"] == 1
    assert uploaded["upload_error"] is None
    assert uploaded["upload_details"]["execution_started"] is False
    assert uploaded["upload_details"]["runtime_mission_id"] == sealed["package"]["wire"]["mission_id"]
    assert len(uploader.calls) == 1

    # Seal another immutable package so a failed transport attempt can be audited separately.
    second = await create_mission_deployment(mission_id, object())
    second_id = __import__("uuid").UUID(second["id"])
    failed_uploader = _ApiUploader(
        error=MissionUploadError(
            "TRANSPORT_UNAVAILABLE",
            "socket closed",
            details={"host": "10.0.0.2"},
        )
    )

    with pytest.raises(HTTPException) as exc:
        await upload_mission_deployment(
            mission_id,
            second_id,
            _request_with_uploader(failed_uploader),
        )
    assert exc.value.status_code == 502

    async with session_factory() as session:
        failed = await session.get(MissionDeployment, second_id)
        assert failed is not None
        assert failed.upload_status == "FAILED"
        assert failed.upload_attempts == 1
        assert failed.upload_error.startswith("TRANSPORT_UNAVAILABLE:")
        assert failed.upload_details["execution_started"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_mission_upload_endpoint_blocks_active_runtime(monkeypatch) -> None:
    async with session_factory() as session:
        await session.execute(delete(MissionDeployment))
        await session.execute(delete(Mission))
        await session.commit()

    active_vehicle = VehicleSnapshot(
        id="vehicle:M3E-ACTIVE",
        sn="M3E-ACTIVE",
        name="M3E",
        model="M3E",
        source="lyrebird",
        online=True,
        sources=("lyrebird",),
        telemetry={
            "mission": {"state": 3, "current_seq": 1, "mission_id": 123},
            "aircraft_state": {
                "failsafe": False,
                "positioning": {
                    "fix": "FIXED",
                    "rtk": {"fix": "FIXED"},
                },
            },
            "safety": {
                "ready_to_takeoff": True,
                "manual_override": False,
            },
            "battery": {"capacity_percent": 80},
        },
    )
    monkeypatch.setattr(
        "app.api_missions._registry",
        lambda request: _DeploymentRegistry(active_vehicle),
    )
    monkeypatch.setattr(
        "app.api_missions.settings.mission_upload_enabled",
        True,
    )

    created = await create_mission(
        MissionCreate(
            name="Active runtime block",
            aircraft_sn="M3E-ACTIVE",
            preferred_executor="DJI_NATIVE",
            items=[
                MissionItemInput(
                    command=16,
                    latitude_deg=49.0,
                    longitude_deg=8.0,
                    altitude_m=50.0,
                )
            ],
        )
    )
    mission_id = __import__("uuid").UUID(created["id"])

    # Sealing also evaluates preflight, so use an inactive runtime for that one operation.
    inactive_vehicle = VehicleSnapshot(
        **{
            **active_vehicle.__dict__,
            "telemetry": {
                **active_vehicle.telemetry,
                "mission": {"state": 2, "current_seq": 0, "mission_id": 0},
            },
        }
    )
    monkeypatch.setattr(
        "app.api_missions._registry",
        lambda request: _DeploymentRegistry(inactive_vehicle),
    )
    sealed = await create_mission_deployment(mission_id, object())
    deployment_id = __import__("uuid").UUID(sealed["id"])

    monkeypatch.setattr(
        "app.api_missions._registry",
        lambda request: _DeploymentRegistry(active_vehicle),
    )
    with pytest.raises(HTTPException) as exc:
        await upload_mission_deployment(
            mission_id,
            deployment_id,
            _request_with_uploader(_ApiUploader()),
        )
    assert exc.value.status_code == 409
    assert "ACTIVE" in str(exc.value.detail)

    async with session_factory() as session:
        deployment = await session.get(MissionDeployment, deployment_id)
        assert deployment is not None
        assert deployment.upload_status == "SEALED"
        assert deployment.upload_attempts == 0



@pytest.mark.asyncio(loop_scope="session")
async def test_recover_interrupted_mission_upload(monkeypatch) -> None:
    async with session_factory() as session:
        await session.execute(delete(MissionDeployment))
        await session.execute(delete(Mission))
        await session.commit()

    vehicle = VehicleSnapshot(
        id="vehicle:M3E-RECOVER",
        sn="M3E-RECOVER",
        name="M3E",
        model="M3E",
        source="lyrebird",
        online=True,
        sources=("lyrebird",),
        telemetry={
            "mission": {"state": 2, "current_seq": 0, "mission_id": 0},
            "aircraft_state": {
                "failsafe": False,
                "positioning": {
                    "fix": "FIXED",
                    "rtk": {"fix": "FIXED"},
                },
            },
            "safety": {
                "ready_to_takeoff": True,
                "manual_override": False,
            },
            "battery": {"capacity_percent": 80},
        },
    )
    monkeypatch.setattr(
        "app.api_missions._registry",
        lambda request: _DeploymentRegistry(vehicle),
    )

    created = await create_mission(
        MissionCreate(
            name="Interrupted upload",
            aircraft_sn="M3E-RECOVER",
            preferred_executor="DJI_NATIVE",
            items=[
                MissionItemInput(
                    command=16,
                    latitude_deg=49.0,
                    longitude_deg=8.0,
                    altitude_m=50.0,
                )
            ],
        )
    )
    mission_id = __import__("uuid").UUID(created["id"])
    sealed = await create_mission_deployment(mission_id, object())
    deployment_id = __import__("uuid").UUID(sealed["id"])

    async with session_factory() as session:
        deployment = await session.get(MissionDeployment, deployment_id)
        assert deployment is not None
        deployment.upload_status = "UPLOADING"
        deployment.upload_attempts = 1
        deployment.upload_details = {}
        await session.commit()

    assert await recover_interrupted_uploads(session_factory) == 1
    assert await recover_interrupted_uploads(session_factory) == 0

    async with session_factory() as session:
        recovered = await session.get(MissionDeployment, deployment_id)
        assert recovered is not None
        assert recovered.upload_status == "UPLOAD_INTERRUPTED"
        assert recovered.upload_attempts == 1
        assert recovered.upload_details["execution_started"] is False
        assert recovered.upload_details["safe_to_retry_same_sealed_package"] is True
        assert "backend restarted" in recovered.upload_error
