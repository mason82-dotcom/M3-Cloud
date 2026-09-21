from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.config import settings
from app.database import session_factory
from app.dji.waylines import compile_mission_wayline, wayline_list_item
from app.dji.wpml import WPMLCompileError
from app.models import Mission


router = APIRouter(
    prefix="/wayline/api/v1",
    tags=["dji-pilot-waylines"],
)


def _response(data=None, *, message: str = "success") -> dict[str, object]:
    return {"code": 0, "message": message, "data": data}


def _validate_workspace(workspace_id: str) -> None:
    configured = settings.dji_pilot_workspace_id.strip()
    if not configured or workspace_id != configured:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DJI workspace not found",
        )


def _validate_token(token: str | None) -> None:
    expected = settings.dji_pilot_api_token
    if not expected or token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid DJI Pilot token",
        )


def _timestamp_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


async def _mission(mission_id: uuid.UUID) -> Mission:
    async with session_factory() as session:
        mission = await session.get(Mission, mission_id)
        if mission is None or mission.status != "READY":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="DJI wayline not found",
            )
        # Detach the data needed after leaving the session.
        return Mission(
            id=mission.id,
            survey_id=mission.survey_id,
            name=mission.name,
            kind=mission.kind,
            source=mission.source,
            status=mission.status,
            aircraft_sn=mission.aircraft_sn,
            preferred_executor=mission.preferred_executor,
            external_ref=mission.external_ref,
            plan_version=mission.plan_version,
            item_count=mission.item_count,
            plan_sha256=mission.plan_sha256,
            plan_json=mission.plan_json,
            created_at=mission.created_at,
            updated_at=mission.updated_at,
        )


@router.get("/workspaces/{workspace_id}/waylines")
async def list_waylines(
    workspace_id: str,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    favorited: bool | None = Query(default=None),
    key: str | None = Query(default=None),
) -> dict[str, object]:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)

    if favorited is True:
        return _response(
            {
                "list": [],
                "pagination": {"page": page, "page_size": page_size, "total": 0},
            }
        )

    async with session_factory() as session:
        statement = (
            select(Mission)
            .where(Mission.status == "READY")
            .order_by(Mission.updated_at.desc(), Mission.id)
        )
        if key:
            statement = statement.where(Mission.name.ilike(f"%{key}%"))
        missions = (await session.scalars(statement)).all()

        exportable: list[dict[str, object]] = []
        for mission in missions:
            try:
                exportable.append(
                    wayline_list_item(
                        mission_id=str(mission.id),
                        name=mission.name,
                        plan=mission.plan_json or {},
                        updated_at_ms=_timestamp_ms(mission.updated_at),
                    )
                )
            except WPMLCompileError:
                continue

    total = len(exportable)
    start = (page - 1) * page_size
    data = exportable[start : start + page_size]
    return _response(
        {
            "list": data,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
            },
        }
    )


@router.get("/workspaces/{workspace_id}/waylines/duplicate-names")
async def duplicate_names(
    workspace_id: str,
    name: Annotated[list[str], Query(min_length=1)],
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> dict[str, object]:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)

    requested = {value for value in name if value}
    if not requested:
        return _response([])

    async with session_factory() as session:
        existing = (
            await session.scalars(
                select(Mission.name).where(Mission.name.in_(sorted(requested)))
            )
        ).all()
    return _response(sorted(set(existing)))


@router.get("/workspaces/{workspace_id}/waylines/{wayline_id}/url")
async def wayline_download_location(
    workspace_id: str,
    wayline_id: uuid.UUID,
    request: Request,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> RedirectResponse:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)
    await _mission(wayline_id)

    location = request.url_for(
        "download_wayline_file",
        workspace_id=workspace_id,
        wayline_id=str(wayline_id),
    )
    return RedirectResponse(url=str(location), status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get(
    "/workspaces/{workspace_id}/waylines/{wayline_id}/download",
    name="download_wayline_file",
)
async def download_wayline_file(
    workspace_id: str,
    wayline_id: uuid.UUID,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> Response:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)
    mission = await _mission(wayline_id)

    try:
        artifact = compile_mission_wayline(
            mission.plan_json or {},
            name=f"{mission.name}-v{mission.plan_version}",
        )
    except WPMLCompileError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return Response(
        content=artifact.kmz,
        media_type="application/vnd.google-earth.kmz",
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "Content-Length": str(len(artifact.kmz)),
            "X-M3Cloud-Plan-SHA256": mission.plan_sha256,
        },
    )
