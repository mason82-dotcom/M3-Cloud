from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.database import session_factory
from app.dji.map_elements import (
    DJIMapValidationError,
    map_element_resource,
    map_ws_event,
    shared_group_id,
    validate_geojson_content,
)
from app.models import DjiMapElement
from app.redis_client import redis_client


logger = logging.getLogger(__name__)
router = APIRouter(tags=["dji-pilot-map"])


class MapResourceBody(BaseModel):
    content: dict[str, Any]
    type: Literal[0, 1, 2]


class MapElementCreateBody(BaseModel):
    id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    resource: MapResourceBody


class MapElementUpdateBody(BaseModel):
    content: dict[str, Any] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)


def _response(data: object | None = None) -> dict[str, object]:
    return {
        "code": 0,
        "message": "success",
        "data": data if data is not None else {},
    }


def _failure(message: str) -> dict[str, object]:
    return {
        "code": -1,
        "message": message,
        "data": {},
    }


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


def _element_output(value: DjiMapElement) -> dict[str, Any]:
    return {
        "id": str(value.id),
        "name": value.name,
        "create_time": _timestamp_ms(value.created_at),
        "update_time": _timestamp_ms(value.updated_at),
        "resource": map_element_resource(
            resource_type=value.resource_type,
            content=value.content,
            user_name=value.user_name,
        ),
    }


async def _publish(event: dict[str, Any]) -> None:
    try:
        await redis_client.publish(
            settings.live_redis_channel,
            json.dumps(event),
        )
    except Exception:
        # Persisting the map edit is authoritative; WS fan-out may recover on
        # the next group refresh/list request.
        logger.warning("Failed to publish DJI map event", exc_info=True)


@router.get("/map/api/v1/workspaces/{workspace_id}/element-groups")
async def list_map_groups(
    workspace_id: str,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
    group_id: str | None = Query(default=None),
    is_distributed: bool | None = Query(default=None),
) -> dict[str, object]:
    del is_distributed
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)

    group = shared_group_id(workspace_id)
    if group_id and group_id != group:
        return _response([])

    async with session_factory() as session:
        elements = (
            await session.scalars(
                select(DjiMapElement)
                .where(
                    DjiMapElement.workspace_id == workspace_id,
                    DjiMapElement.group_id == group,
                )
                .order_by(DjiMapElement.created_at, DjiMapElement.id)
            )
        ).all()

    create_time = (
        min(_timestamp_ms(item.created_at) for item in elements)
        if elements
        else 0
    )
    return _response(
        [
            {
                "id": group,
                "type": 2,
                "name": settings.dji_pilot_workspace_name or "M3-Cloud",
                "is_lock": False,
                "create_time": create_time,
                "elements": [_element_output(item) for item in elements],
            }
        ]
    )


@router.post(
    "/map/api/v1/workspaces/{workspace_id}/element-groups/{group_id}/elements"
)
async def create_map_element(
    workspace_id: str,
    group_id: str,
    body: MapElementCreateBody,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> dict[str, object]:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)

    expected_group = shared_group_id(workspace_id)
    if group_id != expected_group:
        return _failure("Unknown DJI Pilot map element group")

    try:
        content = validate_geojson_content(
            body.resource.content,
            resource_type=body.resource.type,
        )
    except DJIMapValidationError as exc:
        return _failure(str(exc))

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        existing = await session.get(DjiMapElement, body.id)
        if existing is not None:
            return _failure("DJI map element id already exists")

        value = DjiMapElement(
            id=body.id,
            workspace_id=workspace_id,
            group_id=group_id,
            name=body.name,
            resource_type=body.resource.type,
            content=content,
            user_name=settings.dji_pilot_map_user_name,
            created_at=now,
            updated_at=now,
        )
        session.add(value)
        await session.commit()

    resource = map_element_resource(
        resource_type=body.resource.type,
        content=content,
        user_name=settings.dji_pilot_map_user_name,
    )
    await _publish(
        map_ws_event(
            "element_create",
            element_id=str(body.id),
            group_id=group_id,
            name=body.name,
            resource=resource,
        )
    )
    return _response({"id": str(body.id)})


@router.put("/map/api/v1/workspaces/{workspace_id}/elements/{element_id}")
async def update_map_element(
    workspace_id: str,
    element_id: uuid.UUID,
    body: MapElementUpdateBody,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> dict[str, object]:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        value = await session.get(DjiMapElement, element_id)
        if value is None or value.workspace_id != workspace_id:
            return _failure("DJI map element not found")

        if body.content is not None:
            try:
                value.content = validate_geojson_content(
                    body.content,
                    resource_type=value.resource_type,
                )
            except DJIMapValidationError as exc:
                return _failure(str(exc))
        if body.name is not None:
            value.name = body.name
        value.updated_at = now

        resource = map_element_resource(
            resource_type=value.resource_type,
            content=value.content,
            user_name=value.user_name,
        )
        name = value.name
        group_id = value.group_id
        await session.commit()

    await _publish(
        map_ws_event(
            "element_update",
            element_id=str(element_id),
            group_id=group_id,
            name=name,
            resource=resource,
        )
    )
    return _response({"id": str(element_id)})


@router.delete("/map/api/v1/workspaces/{workspace_id}/elements/{element_id}")
async def delete_map_element(
    workspace_id: str,
    element_id: uuid.UUID,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> dict[str, object]:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)

    async with session_factory() as session:
        value = await session.get(DjiMapElement, element_id)
        if value is None or value.workspace_id != workspace_id:
            return _failure("DJI map element not found")
        group_id = value.group_id
        await session.delete(value)
        await session.commit()

    await _publish(
        map_ws_event(
            "element_delete",
            element_id=str(element_id),
            group_id=group_id,
        )
    )
    return _response({"id": str(element_id)})
