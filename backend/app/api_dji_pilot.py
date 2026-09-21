from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from app.config import settings
from app.dji.pilot import build_pilot_bootstrap


router = APIRouter(prefix="/api/v1/dji/pilot", tags=["dji-pilot"])


def _require_bootstrap_token(supplied: str | None) -> None:
    expected = settings.dji_pilot_bootstrap_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="M3CLOUD_DJI_PILOT_BOOTSTRAP_TOKEN is not configured",
        )
    if not secrets.compare_digest(supplied or "", expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Pilot 2 bootstrap token",
        )


def _bootstrap_payload(request: Request) -> dict[str, Any]:
    if not settings.dji_pilot_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DJI Pilot 2 bootstrap is disabled",
        )

    public_base_url = (
        settings.dji_pilot_api_url.strip()
        or str(request.base_url).rstrip("/")
    )
    payload = build_pilot_bootstrap(
        settings,
        public_base_url=public_base_url,
    )
    if not payload["ready"]:
        problems = [
            *[f"missing:{item}" for item in payload["missing"]],
            *[f"invalid:{item}" for item in payload["invalid"]],
        ]
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DJI Pilot 2 bootstrap is incomplete: " + ", ".join(problems),
        )
    return payload


@router.post("/bootstrap")
async def pilot_bootstrap(
    request: Request,
    response: Response,
    x_m3_pilot_bootstrap: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_bootstrap_token(x_m3_pilot_bootstrap)

    # This payload contains DJI license material and broker/API credentials.
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return _bootstrap_payload(request)


@router.get("/status")
async def pilot_status(request: Request) -> dict[str, object]:
    """Non-secret readiness view for operations/diagnostics."""

    public_base_url = (
        settings.dji_pilot_api_url.strip()
        or str(request.base_url).rstrip("/")
    )
    payload = build_pilot_bootstrap(
        settings,
        public_base_url=public_base_url,
    )
    return {
        "enabled": settings.dji_pilot_enabled,
        "mqtt_ingest_enabled": settings.dji_mqtt_enabled,
        "bootstrap_token_configured": bool(settings.dji_pilot_bootstrap_token),
        "ready": bool(
            settings.dji_pilot_enabled
            and settings.dji_pilot_bootstrap_token
            and payload["ready"]
        ),
        "missing": payload["missing"],
        "invalid": payload["invalid"],
        "components": payload["components"],
    }
