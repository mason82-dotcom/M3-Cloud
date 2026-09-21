from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config import settings
from app.dji.cloud_control import (
    DJICloudControlConfigError,
    DJICloudControlGatewayOffline,
    DJICloudControlNotAuthorized,
)
from app.dji.gateway import DJIGatewayNotFound, DJIUnsupportedGateway
from app.dji.liveview import DJILiveView
from app.dji.pilot import build_pilot_bootstrap
from app.dji.services import DJIServiceResultError
from app.dji.transactions import DJITransactionTimeout


router = APIRouter(prefix="/api/v1/dji", tags=["dji-cloud"])


class LiveStartBody(BaseModel):
    video_id: str = Field(min_length=1, max_length=255)
    url_type: Literal[0, 1, 3]
    url: str = Field(min_length=1, max_length=2048)
    video_quality: int = Field(default=0, ge=0, le=4)


class LiveStopBody(BaseModel):
    video_id: str = Field(min_length=1, max_length=255)


class LiveQualityBody(BaseModel):
    video_id: str = Field(min_length=1, max_length=255)
    video_quality: int = Field(ge=0, le=4)


class LiveLensBody(BaseModel):
    video_id: str = Field(min_length=1, max_length=255)
    video_type: Literal["normal", "thermal", "wide", "zoom"]





@router.get("/pilot/bootstrap")
async def pilot_bootstrap(request: Request) -> dict[str, Any]:
    """Configuration consumed by the H5 page embedded in DJI Pilot 2."""

    public_base_url = settings.dji_pilot_api_url.strip() or str(request.base_url).rstrip("/")
    return build_pilot_bootstrap(settings, public_base_url=public_base_url)


def _dji(request: Request):
    return request.app.state.dji_service


def _liveview(request: Request) -> DJILiveView:
    return DJILiveView(_dji(request).services)


async def _gateway_state(request: Request, gateway_sn: str) -> dict[str, Any]:
    state = await _dji(request).telemetry.get(gateway_sn)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DJI gateway state not found",
        )
    return state


def _translate_command_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DJIGatewayNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    if isinstance(exc, (DJIUnsupportedGateway, DJICloudControlGatewayOffline)):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    if isinstance(exc, DJICloudControlNotAuthorized):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    if isinstance(exc, DJICloudControlConfigError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    if isinstance(exc, DJITransactionTimeout):
        return HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
        )
    if isinstance(exc, DJIServiceResultError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "method": exc.response.method,
                "result": exc.response.result,
                "output": exc.response.output,
            },
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"DJI Cloud API command failed: {type(exc).__name__}: {exc}",
    )


@router.get("/gateways/{gateway_sn}/live")
async def gateway_live_state(
    gateway_sn: str,
    request: Request,
) -> dict[str, Any]:
    state = await _gateway_state(request, gateway_sn)
    return {
        "gateway_sn": gateway_sn,
        "live_capacity": state.get("live_capacity"),
        "live_status": state.get("live_status"),
        "source_timestamp_ms": state.get("source_timestamp_ms"),
        "received_at_ms": state.get("received_at_ms"),
    }


@router.post("/gateways/{gateway_sn}/live/start")
async def start_live(
    gateway_sn: str,
    body: LiveStartBody,
    request: Request,
) -> dict[str, Any]:
    try:
        return await _liveview(request).start(
            gateway_sn,
            video_id=body.video_id,
            url_type=body.url_type,
            url=body.url,
            video_quality=body.video_quality,
        )
    except Exception as exc:
        raise _translate_command_error(exc) from exc


@router.post("/gateways/{gateway_sn}/live/stop")
async def stop_live(
    gateway_sn: str,
    body: LiveStopBody,
    request: Request,
) -> dict[str, Any]:
    try:
        return await _liveview(request).stop(gateway_sn, video_id=body.video_id)
    except Exception as exc:
        raise _translate_command_error(exc) from exc


@router.post("/gateways/{gateway_sn}/live/quality")
async def set_live_quality(
    gateway_sn: str,
    body: LiveQualityBody,
    request: Request,
) -> dict[str, Any]:
    try:
        return await _liveview(request).set_quality(
            gateway_sn,
            video_id=body.video_id,
            video_quality=body.video_quality,
        )
    except Exception as exc:
        raise _translate_command_error(exc) from exc


@router.post("/gateways/{gateway_sn}/live/lens")
async def set_live_lens(
    gateway_sn: str,
    body: LiveLensBody,
    request: Request,
) -> dict[str, Any]:
    try:
        return await _liveview(request).set_lens(
            gateway_sn,
            video_id=body.video_id,
            video_type=body.video_type,
        )
    except Exception as exc:
        raise _translate_command_error(exc) from exc



@router.post("/gateways/{gateway_sn}/cloud-control/authorize")
async def authorize_cloud_control(
    gateway_sn: str,
    body: CloudControlAuthorizationBody,
    request: Request,
) -> dict[str, object]:
    try:
        return await _dji(request).cloud_control.request_authorization(
            gateway_sn,
            user_id=body.user_id,
            user_callsign=body.user_callsign,
        )
    except Exception as exc:
        raise _translate_command_error(exc) from exc


@router.post("/gateways/{gateway_sn}/cloud-control/release")
async def release_cloud_control(
    gateway_sn: str,
    request: Request,
) -> dict[str, object]:
    try:
        return await _dji(request).cloud_control.release(gateway_sn)
    except Exception as exc:
        raise _translate_command_error(exc) from exc


@router.post("/gateways/{gateway_sn}/drc/enter")
async def enter_drc_mode(
    gateway_sn: str,
    request: Request,
) -> dict[str, object]:
    try:
        return await _dji(request).cloud_control.enter_drc(gateway_sn)
    except Exception as exc:
        raise _translate_command_error(exc) from exc
