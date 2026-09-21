from __future__ import annotations

import secrets
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response, status

from app.config import settings


router = APIRouter(prefix="/api/v1/dji/pilot", tags=["dji-pilot"])


def _validated_bootstrap() -> dict[str, object]:
    if not settings.dji_pilot_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DJI Pilot 2 bootstrap is disabled",
        )

    missing = [
        name
        for name, value in (
            ("M3CLOUD_DJI_CLOUD_APP_ID", settings.dji_cloud_app_id),
            ("M3CLOUD_DJI_CLOUD_APP_KEY", settings.dji_cloud_app_key),
            ("M3CLOUD_DJI_CLOUD_APP_LICENSE", settings.dji_cloud_app_license),
            ("M3CLOUD_DJI_PILOT_MQTT_URL", settings.dji_pilot_mqtt_url),
            ("M3CLOUD_DJI_WORKSPACE_ID", settings.dji_workspace_id),
        )
        if not value.strip()
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DJI Pilot 2 bootstrap is incomplete: " + ", ".join(missing),
        )

    if not settings.dji_pilot_mqtt_url.startswith(("tcp://", "ws://")):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="M3CLOUD_DJI_PILOT_MQTT_URL must start with tcp:// or ws://",
        )

    try:
        workspace_uuid = str(UUID(settings.dji_workspace_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="M3CLOUD_DJI_WORKSPACE_ID must be a UUID",
        ) from exc

    return {
        "enabled": True,
        "license": {
            "app_id": settings.dji_cloud_app_id,
            "app_key": settings.dji_cloud_app_key,
            "app_license": settings.dji_cloud_app_license,
        },
        "mqtt": {
            "host": settings.dji_pilot_mqtt_url,
            "username": settings.dji_pilot_mqtt_username,
            "password": settings.dji_pilot_mqtt_password,
        },
        "workspace": {
            "id": workspace_uuid,
            "platform_name": settings.dji_platform_name,
            "name": settings.dji_workspace_name,
            "description": settings.dji_workspace_description,
        },
        # M3-Cloud currently implements the primary Pilot-to-Cloud MQTT thing path.
        # Do not make Pilot 2 expose modules whose required DJI HTTPS/WS contracts are not present.
        "modules": {
            "thing": True,
            "api": False,
            "ws": False,
            "map": False,
            "tsa": False,
            "media": False,
            "mission": False,
            "liveshare": False,
        },
    }


@router.post("/bootstrap")
async def pilot_bootstrap(
    response: Response,
    x_m3_pilot_bootstrap: str | None = Header(default=None),
) -> dict[str, object]:
    expected = settings.dji_pilot_bootstrap_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="M3CLOUD_DJI_PILOT_BOOTSTRAP_TOKEN is not configured",
        )
    supplied = x_m3_pilot_bootstrap or ""
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Pilot 2 bootstrap token",
        )

    # The response intentionally contains DJI license material and Pilot MQTT credentials.
    # It must never be cached by Pilot WebView, nginx, browsers or intermediate proxies.
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return _validated_bootstrap()


@router.get("/status")
async def pilot_status() -> dict[str, object]:
    """Safe readiness view: never returns license, MQTT password or bootstrap token."""
    configured = {
        "app_id": bool(settings.dji_cloud_app_id.strip()),
        "app_key": bool(settings.dji_cloud_app_key.strip()),
        "app_license": bool(settings.dji_cloud_app_license.strip()),
        "mqtt_url": bool(settings.dji_pilot_mqtt_url.strip()),
        "workspace_id": bool(settings.dji_workspace_id.strip()),
        "bootstrap_token": bool(settings.dji_pilot_bootstrap_token),
    }
    return {
        "enabled": settings.dji_pilot_enabled,
        "mqtt_ingest_enabled": settings.dji_mqtt_enabled,
        "configured": configured,
        "ready": settings.dji_pilot_enabled
        and settings.dji_mqtt_enabled
        and all(configured.values()),
        "modules": {
            "thing": True,
            "api": False,
            "ws": False,
            "map": False,
            "tsa": False,
            "media": False,
            "mission": False,
            "liveshare": False,
        },
    }
