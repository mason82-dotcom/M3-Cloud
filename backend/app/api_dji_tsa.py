from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from app.config import settings
from app.dji.pilot_ws import DJIPilotWebSocketHub
from app.dji.registry import DeviceRegistry
from app.dji.tsa import build_topologies
from app.redis_client import redis_client


router = APIRouter(tags=["dji-pilot-tsa"])


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


@router.get("/manage/api/v1/workspaces/{workspace_id}/devices/topologies")
async def device_topologies(
    workspace_id: str,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> dict[str, object]:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)

    devices = await DeviceRegistry(redis_client).list_devices()
    return {
        "code": 0,
        "message": "success",
        "data": {"list": build_topologies(devices)},
    }


@router.websocket("/ws/dji-pilot")
async def dji_pilot_websocket(websocket: WebSocket) -> None:
    token = websocket.query_params.get("x-auth-token")
    expected = settings.dji_pilot_api_token
    if not expected or token != expected:
        await websocket.close(code=1008)
        return

    hub: DJIPilotWebSocketHub = websocket.app.state.dji_pilot_ws_hub
    await hub.connect(websocket)
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(websocket)
