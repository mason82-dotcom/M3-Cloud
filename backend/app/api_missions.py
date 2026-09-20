from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import json

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api_operations import _registry
from app.config import settings
from app.database import session_factory
from app.missions.deployment import build_deployment_package, deployment_sha256
from app.missions.uploader import MissionUploadError
from app.missions.plans import (
    compatibility,
    mission_state_name,
    normalize_plan,
    plan_sha256,
)
from app.missions.preflight import evaluate_preflight
from app.models import Mission, MissionDeployment, MissionRevision, Survey


router = APIRouter(prefix="/api/v1/missions", tags=["missions"])


class MissionItemInput(BaseModel):
    seq: int | None = Field(default=None, ge=0)
    frame: int = Field(default=6, ge=0, le=255)
    command: int = Field(ge=0)
    param1: float | None = None
    param2: float | None = None
    param3: float | None = None
    param4: float | None = None
    latitude_deg: float = 0.0
    longitude_deg: float = 0.0
    altitude_m: float = 0.0
    autocontinue: bool = True


class MissionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    survey_id: uuid.UUID | None = None
    aircraft_sn: str | None = Field(default=None, max_length=128)
    preferred_executor: Literal["DJI_NATIVE", "ONBOARD"] | None = None
    items: list[MissionItemInput] = Field(default_factory=list)


class MissionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    survey_id: uuid.UUID | None = None
    aircraft_sn: str | None = Field(default=None, max_length=128)
    preferred_executor: Literal["DJI_NATIVE", "ONBOARD"] | None = None
    status: Literal["DRAFT", "READY", "ARCHIVED"] | None = None
    items: list[MissionItemInput] | None = None


def _base_payload(mission: Mission) -> dict[str, Any]:
    return {
        "id": str(mission.id),
        "survey_id": str(mission.survey_id) if mission.survey_id else None,
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
        "compatibility": compatibility(mission.plan_json or {}),
        "created_at": mission.created_at.isoformat(),
        "updated_at": mission.updated_at.isoformat(),
    }


async def _runtime_by_aircraft(request: Request) -> dict[str, dict[str, Any]]:
    vehicles = await _registry(request).list_vehicles()
    result: dict[str, dict[str, Any]] = {}

    for vehicle in vehicles:
        telemetry = vehicle.telemetry if isinstance(vehicle.telemetry, dict) else {}
        mission = telemetry.get("mission")
        reach = telemetry.get("reach")
        if not isinstance(mission, dict) and not isinstance(reach, dict):
            continue

        state_code = mission.get("state") if isinstance(mission, dict) else None
        result[vehicle.sn] = {
            "available": True,
            "source": vehicle.source,
            "state_code": state_code,
            "state": mission_state_name(state_code),
            "current_seq": mission.get("current_seq") if isinstance(mission, dict) else None,
            "mission_id": mission.get("mission_id") if isinstance(mission, dict) else None,
            "waypoint_reached_seq": (
                reach.get("waypoint_seq") if isinstance(reach, dict) else None
            ),
            "runtime_plan_identity": "UNVERIFIED",
            "linked_to_persisted_plan": False,
        }
    return result


async def _mission_payload(
    mission: Mission,
    runtime: dict[str, dict[str, Any]],
    deployments: list[MissionDeployment] | None = None,
) -> dict[str, Any]:
    payload = _base_payload(mission)
    observed = (
        dict(runtime.get(mission.aircraft_sn) or {})
        if mission.aircraft_sn
        else None
    )

    if observed is not None:
        observed_id = observed.get("mission_id")
        matched = None
        if isinstance(observed_id, int) and observed_id != 0:
            for deployment in reversed(deployments or []):
                package = deployment.package_json or {}
                wire = package.get("wire") if isinstance(package, dict) else None
                expected = wire.get("mission_id") if isinstance(wire, dict) else None
                if expected == observed_id:
                    matched = deployment
                    break

        if matched is not None:
            observed["runtime_plan_identity"] = "VERIFIED"
            observed["linked_to_persisted_plan"] = True
            observed["deployment_id"] = str(matched.id)
            observed["revision_version"] = matched.revision_version
            observed["plan_sha256"] = matched.plan_sha256

    payload["runtime"] = observed
    return payload


async def _validate_survey(session, survey_id: uuid.UUID | None) -> None:
    if survey_id is None:
        return
    if await session.get(Survey, survey_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Survey not found",
        )


def _input_plan(items: list[MissionItemInput]) -> dict[str, object]:
    try:
        return normalize_plan(
            [
                {
                    **item.model_dump(exclude_none=True),
                    "seq": item.seq if item.seq is not None else index,
                }
                for index, item in enumerate(items)
            ]
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("")
async def list_missions(
    request: Request,
    survey_id: uuid.UUID | None = None,
    aircraft_sn: str | None = None,
    include_archived: bool = False,
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[dict[str, Any]]:
    statement = select(Mission).order_by(Mission.updated_at.desc()).limit(limit)
    if survey_id is not None:
        statement = statement.where(Mission.survey_id == survey_id)
    if aircraft_sn:
        statement = statement.where(Mission.aircraft_sn == aircraft_sn)
    if not include_archived:
        statement = statement.where(Mission.status != "ARCHIVED")

    async with session_factory() as session:
        missions = (await session.scalars(statement)).all()
        ids = [mission.id for mission in missions]
        deployments = (
            await session.scalars(
                select(MissionDeployment)
                .where(MissionDeployment.mission_id.in_(ids))
                .order_by(MissionDeployment.created_at, MissionDeployment.id)
            )
        ).all() if ids else []

    by_mission: dict[uuid.UUID, list[MissionDeployment]] = {}
    for deployment in deployments:
        by_mission.setdefault(deployment.mission_id, []).append(deployment)

    runtime = await _runtime_by_aircraft(request)
    return [
        await _mission_payload(
            mission,
            runtime,
            by_mission.get(mission.id, []),
        )
        for mission in missions
    ]


@router.get("/{mission_id}")
async def mission_detail(
    mission_id: uuid.UUID,
    request: Request,
) -> dict[str, Any]:
    async with session_factory() as session:
        mission = await session.get(Mission, mission_id)
        if mission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mission not found",
            )
        deployments = (
            await session.scalars(
                select(MissionDeployment)
                .where(MissionDeployment.mission_id == mission_id)
                .order_by(MissionDeployment.created_at, MissionDeployment.id)
            )
        ).all()
    runtime = await _runtime_by_aircraft(request)
    return await _mission_payload(mission, runtime, deployments)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_mission(body: MissionCreate) -> dict[str, Any]:
    plan = _input_plan(body.items)
    now = datetime.now(timezone.utc)
    mission = Mission(
        survey_id=body.survey_id,
        name=body.name.strip(),
        kind="WAYLINE",
        source="M3_CLOUD",
        status="READY" if body.items else "DRAFT",
        aircraft_sn=body.aircraft_sn.strip() if body.aircraft_sn else None,
        preferred_executor=body.preferred_executor,
        external_ref=None,
        plan_version=1,
        item_count=len(body.items),
        plan_sha256=plan_sha256(plan),
        plan_json=plan,
        created_at=now,
        updated_at=now,
    )

    async with session_factory() as session:
        await _validate_survey(session, body.survey_id)
        if body.survey_id is not None:
            duplicate = await session.scalar(
                select(Mission).where(
                    Mission.survey_id == body.survey_id,
                    Mission.name == mission.name,
                )
            )
            if duplicate is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Mission name already exists in survey",
                )
        session.add(mission)
        await session.flush()
        session.add(
            MissionRevision(
                mission_id=mission.id,
                version=mission.plan_version,
                plan_sha256=mission.plan_sha256,
                item_count=mission.item_count,
                plan_json=mission.plan_json,
                created_at=now,
            )
        )
        await session.commit()
        await session.refresh(mission)
        return _base_payload(mission)


@router.patch("/{mission_id}")
async def update_mission(
    mission_id: uuid.UUID,
    body: MissionUpdate,
) -> dict[str, Any]:
    async with session_factory() as session:
        mission = await session.get(Mission, mission_id)
        if mission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mission not found",
            )

        values = body.model_dump(exclude_unset=True)
        if "survey_id" in values:
            await _validate_survey(session, body.survey_id)
            mission.survey_id = body.survey_id
        if "name" in values and body.name is not None:
            mission.name = body.name.strip()
        if "aircraft_sn" in values:
            mission.aircraft_sn = (
                body.aircraft_sn.strip() if body.aircraft_sn else None
            )
        if "preferred_executor" in values:
            mission.preferred_executor = body.preferred_executor

        if body.items is not None:
            plan = _input_plan(body.items)
            mission.plan_json = plan
            mission.plan_sha256 = plan_sha256(plan)
            mission.item_count = len(body.items)
            mission.plan_version += 1
            mission.status = "READY" if body.items else "DRAFT"
            session.add(
                MissionRevision(
                    mission_id=mission.id,
                    version=mission.plan_version,
                    plan_sha256=mission.plan_sha256,
                    item_count=mission.item_count,
                    plan_json=mission.plan_json,
                    created_at=datetime.now(timezone.utc),
                )
            )

        if body.status is not None:
            if body.status == "READY" and mission.item_count == 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Empty mission cannot be READY",
                )
            mission.status = body.status

        if mission.survey_id is not None:
            duplicate = await session.scalar(
                select(Mission).where(
                    Mission.survey_id == mission.survey_id,
                    Mission.name == mission.name,
                    Mission.id != mission.id,
                )
            )
            if duplicate is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Mission name already exists in survey",
                )

        mission.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(mission)
        return _base_payload(mission)


def _revision_payload(revision: MissionRevision) -> dict[str, Any]:
    return {
        "mission_id": str(revision.mission_id),
        "version": revision.version,
        "plan_sha256": revision.plan_sha256,
        "item_count": revision.item_count,
        "plan": revision.plan_json,
        "compatibility": compatibility(revision.plan_json or {}),
        "created_at": revision.created_at.isoformat(),
    }


@router.get("/{mission_id}/revisions")
async def mission_revisions(
    mission_id: uuid.UUID,
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        if await session.get(Mission, mission_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mission not found",
            )
        revisions = (
            await session.scalars(
                select(MissionRevision)
                .where(MissionRevision.mission_id == mission_id)
                .order_by(MissionRevision.version)
            )
        ).all()
        return [_revision_payload(revision) for revision in revisions]


@router.get("/{mission_id}/revisions/{version}")
async def mission_revision(
    mission_id: uuid.UUID,
    version: int,
) -> dict[str, Any]:
    async with session_factory() as session:
        revision = await session.get(MissionRevision, (mission_id, version))
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mission revision not found",
            )
        return _revision_payload(revision)


@router.get("/{mission_id}/revisions/{version}/download")
async def download_mission_revision(
    mission_id: uuid.UUID,
    version: int,
) -> Response:
    revision = await mission_revision(mission_id, version)
    payload = json.dumps(
        revision,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return Response(
        content=payload,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="m3-mission-{mission_id}-v{version}.json"'
            ),
            "Content-Length": str(len(payload)),
        },
    )


@router.get("/{mission_id}/preflight")
async def mission_preflight(
    mission_id: uuid.UUID,
    request: Request,
) -> dict[str, Any]:
    async with session_factory() as session:
        mission = await session.get(Mission, mission_id)
        if mission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mission not found",
            )

    vehicle = None
    if mission.aircraft_sn:
        vehicles = await _registry(request).list_vehicles()
        vehicle = next(
            (item for item in vehicles if item.sn == mission.aircraft_sn),
            None,
        )
    return evaluate_preflight(mission, vehicle)



def _deployment_payload(deployment: MissionDeployment) -> dict[str, Any]:
    return {
        "id": str(deployment.id),
        "mission_id": str(deployment.mission_id),
        "revision_version": deployment.revision_version,
        "plan_sha256": deployment.plan_sha256,
        "aircraft_sn": deployment.aircraft_sn,
        "preferred_executor": deployment.preferred_executor,
        "package_sha256": deployment.package_sha256,
        "package": deployment.package_json,
        "upload_status": deployment.upload_status,
        "upload_attempts": deployment.upload_attempts,
        "last_upload_at": deployment.last_upload_at.isoformat() if deployment.last_upload_at else None,
        "uploaded_at": deployment.uploaded_at.isoformat() if deployment.uploaded_at else None,
        "upload_error": deployment.upload_error,
        "upload_details": deployment.upload_details or {},
        "upload_action_available": (
            settings.mission_upload_enabled
            and isinstance(deployment.package_json, dict)
            and isinstance(deployment.package_json.get("handoff"), dict)
            and deployment.package_json["handoff"].get("upload_enabled") is True
            and deployment.upload_status not in {"UPLOADING", "UPLOADED"}
        ),
        "created_at": deployment.created_at.isoformat(),
    }


@router.get("/{mission_id}/deployments")
async def mission_deployments(
    mission_id: uuid.UUID,
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        if await session.get(Mission, mission_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mission not found",
            )
        deployments = (
            await session.scalars(
                select(MissionDeployment)
                .where(MissionDeployment.mission_id == mission_id)
                .order_by(MissionDeployment.created_at, MissionDeployment.id)
            )
        ).all()
        return [_deployment_payload(item) for item in deployments]


@router.post(
    "/{mission_id}/deployments",
    status_code=status.HTTP_201_CREATED,
)
async def create_mission_deployment(
    mission_id: uuid.UUID,
    request: Request,
) -> dict[str, Any]:
    async with session_factory() as session:
        mission = await session.get(Mission, mission_id)
        if mission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mission not found",
            )
        revision = await session.get(
            MissionRevision,
            (mission_id, mission.plan_version),
        )
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Current mission revision is missing",
            )

        if mission.status != "READY":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only READY missions can be sealed for handoff",
            )
        if not mission.aircraft_sn:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Mission has no assigned aircraft",
            )

        vehicles = await _registry(request).list_vehicles()
        vehicle = next(
            (item for item in vehicles if item.sn == mission.aircraft_sn),
            None,
        )
        preflight = evaluate_preflight(mission, vehicle)
        if not preflight["checks_passed"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Mission preflight has blocking checks",
                    "preflight": preflight,
                },
            )

        compat = compatibility(revision.plan_json or {})
        if not compat["lyrebird_mavlink_upload_compatible"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Mission contains commands outside the Lyrebird upload surface",
                    "compatibility": compat,
                },
            )

        deployment_id = uuid.uuid4()
        created_at = datetime.now(timezone.utc)
        package = build_deployment_package(
            mission,
            revision,
            deployment_id=deployment_id,
            created_at=created_at,
            preflight=preflight,
        )
        package_hash = deployment_sha256(package)

        deployment = MissionDeployment(
            id=deployment_id,
            mission_id=mission.id,
            revision_version=revision.version,
            plan_sha256=revision.plan_sha256,
            aircraft_sn=mission.aircraft_sn,
            preferred_executor=mission.preferred_executor,
            package_sha256=package_hash,
            package_json=package,
            created_at=created_at,
        )
        session.add(deployment)
        await session.commit()
        await session.refresh(deployment)
        return _deployment_payload(deployment)


@router.get("/{mission_id}/deployments/{deployment_id}")
async def mission_deployment(
    mission_id: uuid.UUID,
    deployment_id: uuid.UUID,
) -> dict[str, Any]:
    async with session_factory() as session:
        deployment = await session.get(MissionDeployment, deployment_id)
        if deployment is None or deployment.mission_id != mission_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mission deployment not found",
            )
        return _deployment_payload(deployment)


@router.get("/{mission_id}/deployments/{deployment_id}/download")
async def download_mission_deployment(
    mission_id: uuid.UUID,
    deployment_id: uuid.UUID,
) -> Response:
    deployment = await mission_deployment(mission_id, deployment_id)
    payload = json.dumps(
        deployment,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return Response(
        content=payload,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="m3-mission-handoff-{mission_id}-{deployment_id}.json"'
            ),
            "Content-Length": str(len(payload)),
        },
    )



@router.post("/{mission_id}/deployments/{deployment_id}/upload")
async def upload_mission_deployment(
    mission_id: uuid.UUID,
    deployment_id: uuid.UUID,
    request: Request,
) -> dict[str, Any]:
    """Upload a sealed plan into Lyrebird's mission store. This never starts execution."""

    if not settings.mission_upload_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Mission upload is disabled by server configuration",
        )

    async with session_factory() as session:
        deployment = await session.get(MissionDeployment, deployment_id)
        if deployment is None or deployment.mission_id != mission_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mission deployment not found",
            )
        if deployment.upload_status == "UPLOADED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Mission deployment was already uploaded",
            )
        if deployment.upload_status == "UPLOADING":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Mission deployment upload is already in progress",
            )

        package = deployment.package_json or {}
        handoff = package.get("handoff") if isinstance(package, dict) else None
        if not isinstance(handoff, dict) or handoff.get("upload_enabled") is not True:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This sealed deployment is not upload-enabled",
            )
        if handoff.get("execution_enabled") is not False:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Deployment execution policy is not disabled",
            )

        vehicles = await _registry(request).list_vehicles()
        vehicle = next(
            (item for item in vehicles if item.sn == deployment.aircraft_sn),
            None,
        )
        if vehicle is None or not vehicle.online:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Assigned aircraft is not online",
            )

        telemetry = vehicle.telemetry if isinstance(vehicle.telemetry, dict) else {}
        mission_runtime = telemetry.get("mission")
        state_code = (
            mission_runtime.get("state")
            if isinstance(mission_runtime, dict)
            else None
        )
        state_name = mission_state_name(state_code)
        if state_name in {"ACTIVE", "PAUSED"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Aircraft mission runtime is {state_name}; upload would replace an active plan",
            )

        now = datetime.now(timezone.utc)
        deployment.upload_status = "UPLOADING"
        deployment.upload_attempts += 1
        deployment.last_upload_at = now
        deployment.upload_error = None
        deployment.upload_details = {}
        await session.commit()

    uploader = getattr(request.app.state, "mission_uploader", None)
    if uploader is None:
        error = MissionUploadError(
            "UPLOADER_UNAVAILABLE",
            "Mission uploader is not available",
        )
    else:
        error = None

    try:
        if error is not None:
            raise error
        result = await uploader.upload(
            package,
            aircraft_sn=deployment.aircraft_sn,
            preferred_executor=deployment.preferred_executor,
        )
    except MissionUploadError as exc:
        async with session_factory() as session:
            failed = await session.get(MissionDeployment, deployment_id)
            if failed is not None:
                failed.upload_status = "FAILED"
                failed.upload_error = f"{exc.code}: {exc}"
                failed.upload_details = {
                    "code": exc.code,
                    **exc.details,
                    "execution_started": False,
                }
                await session.commit()

        conflict_codes = {
            "PACKAGE_NOT_UPLOADABLE",
            "PACKAGE_EXECUTION_POLICY",
            "WIRE_INVALID",
            "WIRE_EMPTY",
            "WIRE_SEQUENCE",
            "NO_LYREBIRD_HOSTS",
            "AIRCRAFT_NOT_FOUND",
            "MAVLINK_ROUTE_UNAVAILABLE",
            "EXECUTOR_UNSUPPORTED",
            "EXECUTOR_UNVERIFIED",
            "EXECUTOR_MISMATCH",
            "REQUEST_OUT_OF_RANGE",
        }
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
                if exc.code in conflict_codes
                else status.HTTP_502_BAD_GATEWAY
            ),
            detail={
                "message": str(exc),
                "code": exc.code,
                "details": exc.details,
            },
        ) from exc

    async with session_factory() as session:
        uploaded = await session.get(MissionDeployment, deployment_id)
        if uploaded is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mission deployment disappeared after upload",
            )
        uploaded.upload_status = "UPLOADED"
        uploaded.uploaded_at = datetime.now(timezone.utc)
        uploaded.upload_error = None
        uploaded.upload_details = result.as_dict()
        await session.commit()
        await session.refresh(uploaded)
        return _deployment_payload(uploaded)
