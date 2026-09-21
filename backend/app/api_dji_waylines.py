from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.database import session_factory
from app.dji.storage_sts import (
    pilot_object_key_allowed,
    presign_pilot_object,
)
from app.dji.waylines import (
    compile_mission_wayline,
    inspect_native_wayline_object,
    native_wayline_list_item,
    validate_native_wayline_metadata,
    wayline_list_item,
)
from app.dji.wpml import WPMLCompileError
from app.models import DjiWaylineFile, Mission


router = APIRouter(
    prefix="/wayline/api/v1",
    tags=["dji-pilot-waylines"],
)


class WaylineUploadMetadata(BaseModel):
    drone_model_key: str = Field(min_length=1, max_length=64)
    payload_model_keys: list[str]
    template_types: list[int]


class WaylineUploadCallback(BaseModel):
    object_key: str = Field(min_length=1, max_length=1024)
    name: str = Field(min_length=1, max_length=255)
    metadata: WaylineUploadMetadata


def _response(
    data: object | None = None,
    *,
    code: int = 0,
    message: str = "success",
) -> dict[str, object]:
    return {
        "code": code,
        "message": message,
        "data": data if data is not None else {},
    }


def _failure(message: str) -> dict[str, object]:
    return _response({}, code=-1, message=message)


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


async def _mission(mission_id: uuid.UUID) -> Mission | None:
    async with session_factory() as session:
        mission = await session.get(Mission, mission_id)
        if mission is None or mission.status != "READY":
            return None
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
            dji_favorited=mission.dji_favorited,
            plan_version=mission.plan_version,
            item_count=mission.item_count,
            plan_sha256=mission.plan_sha256,
            plan_json=mission.plan_json,
            created_at=mission.created_at,
            updated_at=mission.updated_at,
        )


async def _native_wayline(
    workspace_id: str,
    wayline_id: uuid.UUID,
) -> DjiWaylineFile | None:
    async with session_factory() as session:
        value = await session.get(DjiWaylineFile, wayline_id)
        if value is None or value.workspace_id != workspace_id:
            return None
        return DjiWaylineFile(
            id=value.id,
            workspace_id=value.workspace_id,
            name=value.name,
            object_key=value.object_key,
            bucket=value.bucket,
            drone_model_key=value.drone_model_key,
            payload_model_keys=list(value.payload_model_keys or []),
            template_types=list(value.template_types or []),
            favorited=value.favorited,
            sha256=value.sha256,
            size_bytes=value.size_bytes,
            source=value.source,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )


def _matches_filters(
    item: dict[str, Any],
    *,
    favorited: bool | None,
    template_type: list[int] | None,
    drone_model_keys: list[str] | None,
    payload_model_key: list[str] | None,
    action_type: int | None,
    key: str | None,
) -> bool:
    if favorited is not None and bool(item.get("favorited")) is not favorited:
        return False

    if template_type:
        actual = set(item.get("template_types") or [])
        if not actual.intersection(template_type):
            return False

    if drone_model_keys and item.get("drone_model_key") not in set(drone_model_keys):
        return False

    if payload_model_key:
        actual_payloads = set(item.get("payload_model_keys") or [])
        if not actual_payloads.intersection(payload_model_key):
            return False

    if action_type is not None and int(item.get("action_type") or 0) != action_type:
        return False

    if key and key.casefold() not in str(item.get("name") or "").casefold():
        return False

    return True


def _sort_waylines(items: list[dict[str, Any]], order_by: str | None) -> None:
    value = (order_by or "update_time desc").strip().lower()
    if value in {"name asc", "name"}:
        items.sort(key=lambda item: str(item.get("name") or "").casefold())
        return
    if value == "name desc":
        items.sort(
            key=lambda item: str(item.get("name") or "").casefold(),
            reverse=True,
        )
        return
    if value == "update_time asc":
        items.sort(key=lambda item: int(item.get("update_time") or 0))
        return

    # Unknown order expressions intentionally fall back to the safe documented
    # default instead of being interpolated into SQL.
    items.sort(
        key=lambda item: int(item.get("update_time") or 0),
        reverse=True,
    )


@router.get("/workspaces/{workspace_id}/waylines")
async def list_waylines(
    workspace_id: str,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    favorited: bool | None = Query(default=None),
    order_by: str | None = Query(default=None),
    key: str | None = Query(default=None),
    template_type: list[int] | None = Query(default=None),
    drone_model_keys: list[str] | None = Query(default=None),
    payload_model_key: list[str] | None = Query(default=None),
    action_type: int | None = Query(default=None, ge=0),
) -> dict[str, object]:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)

    async with session_factory() as session:
        missions = (
            await session.scalars(
                select(Mission).where(Mission.status == "READY")
            )
        ).all()
        native = (
            await session.scalars(
                select(DjiWaylineFile).where(
                    DjiWaylineFile.workspace_id == workspace_id
                )
            )
        ).all()

    items: list[dict[str, Any]] = []
    for mission in missions:
        try:
            item = wayline_list_item(
                mission_id=str(mission.id),
                name=mission.name,
                plan=mission.plan_json or {},
                updated_at_ms=_timestamp_ms(mission.updated_at),
                favorited=mission.dji_favorited,
            )
        except WPMLCompileError:
            continue
        if _matches_filters(
            item,
            favorited=favorited,
            template_type=template_type,
            drone_model_keys=drone_model_keys,
            payload_model_key=payload_model_key,
            action_type=action_type,
            key=key,
        ):
            items.append(item)

    for value in native:
        item = native_wayline_list_item(
            wayline_id=str(value.id),
            name=value.name,
            drone_model_key=value.drone_model_key,
            payload_model_keys=list(value.payload_model_keys or []),
            template_types=list(value.template_types or []),
            favorited=value.favorited,
            updated_at_ms=_timestamp_ms(value.updated_at),
        )
        if _matches_filters(
            item,
            favorited=favorited,
            template_type=template_type,
            drone_model_keys=drone_model_keys,
            payload_model_key=payload_model_key,
            action_type=action_type,
            key=key,
        ):
            items.append(item)

    _sort_waylines(items, order_by)
    total = len(items)
    start = (page - 1) * page_size
    data = items[start : start + page_size]
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
        mission_names = (
            await session.scalars(
                select(Mission.name).where(Mission.name.in_(sorted(requested)))
            )
        ).all()
        native_names = (
            await session.scalars(
                select(DjiWaylineFile.name).where(
                    DjiWaylineFile.workspace_id == workspace_id,
                    DjiWaylineFile.name.in_(sorted(requested)),
                )
            )
        ).all()

    return _response(sorted(set(mission_names) | set(native_names)))


@router.post("/workspaces/{workspace_id}/upload-callback")
async def wayline_upload_callback(
    workspace_id: str,
    body: WaylineUploadCallback,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> dict[str, object]:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)

    if not pilot_object_key_allowed(workspace_id, body.object_key):
        return _failure("object_key is outside the DJI Pilot workspace prefix")

    bucket = settings.dji_pilot_storage_bucket.strip() or "m3-media"
    try:
        inspection = await asyncio.to_thread(
            inspect_native_wayline_object,
            settings,
            bucket=bucket,
            object_key=body.object_key,
        )
        validate_native_wayline_metadata(
            inspection,
            drone_model_key=body.metadata.drone_model_key,
            payload_model_keys=body.metadata.payload_model_keys,
            template_types=body.metadata.template_types,
        )
    except Exception as exc:
        return _failure(f"DJI wayline validation failed: {exc}")

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        value = await session.scalar(
            select(DjiWaylineFile).where(
                DjiWaylineFile.workspace_id == workspace_id,
                DjiWaylineFile.object_key == body.object_key,
            )
        )
        if value is None:
            value = DjiWaylineFile(
                workspace_id=workspace_id,
                name=body.name,
                object_key=body.object_key,
                bucket=bucket,
                drone_model_key=inspection.drone_model_key,
                payload_model_keys=inspection.payload_model_keys,
                template_types=inspection.template_types,
                favorited=False,
                sha256=inspection.sha256,
                size_bytes=inspection.size_bytes,
                source="DJI_PILOT2",
                created_at=now,
                updated_at=now,
            )
            session.add(value)
        else:
            value.name = body.name
            value.bucket = bucket
            value.drone_model_key = inspection.drone_model_key
            value.payload_model_keys = inspection.payload_model_keys
            value.template_types = inspection.template_types
            value.sha256 = inspection.sha256
            value.size_bytes = inspection.size_bytes
            value.updated_at = now

        await session.commit()
        await session.refresh(value)
        wayline_id = str(value.id)

    return _response({"id": wayline_id})


@router.get("/workspaces/{workspace_id}/waylines/{wayline_id}/url")
async def wayline_download_location(
    workspace_id: str,
    wayline_id: uuid.UUID,
    request: Request,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> RedirectResponse:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)

    native = await _native_wayline(workspace_id, wayline_id)
    if native is not None:
        try:
            location = await asyncio.to_thread(
                presign_pilot_object,
                settings,
                bucket=native.bucket,
                object_key=native.object_key,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Unable to create DJI wayline download URL: {exc}",
            ) from exc
        return RedirectResponse(
            url=location,
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    mission = await _mission(wayline_id)
    if mission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DJI wayline not found",
        )

    location = request.url_for(
        "download_wayline_file",
        workspace_id=workspace_id,
        wayline_id=str(wayline_id),
    )
    return RedirectResponse(
        url=str(location),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


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
    if mission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="M3-Cloud generated wayline not found",
        )

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


async def _set_favorites(
    workspace_id: str,
    ids: list[uuid.UUID],
    *,
    favorited: bool,
) -> list[str]:
    updated: list[str] = []
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        for wayline_id in ids:
            native = await session.get(DjiWaylineFile, wayline_id)
            if native is not None and native.workspace_id == workspace_id:
                native.favorited = favorited
                native.updated_at = now
                updated.append(str(wayline_id))
                continue

            mission = await session.get(Mission, wayline_id)
            if mission is not None and mission.status == "READY":
                mission.dji_favorited = favorited
                updated.append(str(wayline_id))

        await session.commit()
    return updated


@router.post("/workspaces/{workspace_id}/favorites")
async def favorite_waylines(
    workspace_id: str,
    id: Annotated[list[uuid.UUID], Query(min_length=1)],
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> dict[str, object]:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)
    updated = await _set_favorites(workspace_id, id, favorited=True)
    if not updated:
        return _failure("No matching DJI waylines found")
    return _response({"id": updated})


@router.delete("/workspaces/{workspace_id}/favorites")
async def unfavorite_waylines(
    workspace_id: str,
    id: Annotated[list[uuid.UUID], Query(min_length=1)],
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> dict[str, object]:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)
    updated = await _set_favorites(workspace_id, id, favorited=False)
    if not updated:
        return _failure("No matching DJI waylines found")
    return _response({"id": updated})
