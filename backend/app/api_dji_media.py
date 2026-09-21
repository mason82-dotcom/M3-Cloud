from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.database import session_factory
from app.dji.media import (
    classify_pilot_media,
    dji_metadata_json,
    inspect_uploaded_object,
    normalized_capture_time,
)
from app.dji.storage_sts import (
    DJIPilotStorageError,
    issue_pilot_sts_credentials,
    pilot_object_key_allowed,
    pilot_storage_ready,
)
from app.models import MediaAsset


router = APIRouter(tags=["dji-pilot-media"])


class MediaExtension(BaseModel):
    drone_model_key: str = Field(min_length=1, max_length=64)
    is_original: bool
    payload_model_key: str = Field(min_length=1, max_length=64)
    tinny_fingerprint: str = Field(min_length=1, max_length=512)
    sn: str = Field(min_length=1, max_length=128)
    file_group_id: str | None = Field(default=None, max_length=128)


class FastUploadBody(BaseModel):
    ext: MediaExtension
    fingerprint: str = Field(min_length=1, max_length=512)
    name: str = Field(min_length=1, max_length=512)
    path: str | None = Field(default=None, max_length=1024)


class TinyFingerprintBody(BaseModel):
    tiny_fingerprints: list[str]


class ShootPosition(BaseModel):
    lat: float
    lng: float


class MediaMetadata(BaseModel):
    absolute_altitude: float
    created_time: datetime
    gimbal_yaw_degree: float
    relative_altitude: float
    shoot_position: ShootPosition


class UploadCallbackBody(BaseModel):
    result: int = 0
    ext: MediaExtension
    fingerprint: str = Field(min_length=1, max_length=512)
    metadata: MediaMetadata
    name: str = Field(min_length=1, max_length=512)
    object_key: str = Field(min_length=1, max_length=1024)
    path: str | None = Field(default=None, max_length=1024)
    sub_file_type: int = Field(default=0, ge=0)


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


def _success(data=None) -> dict[str, object]:
    return {"code": 0, "message": "success", "data": data if data is not None else {}}


def _failure(message: str) -> dict[str, object]:
    return {"code": -1, "message": message, "data": {}}


@router.post("/storage/api/v1/workspaces/{workspace_id}/sts")
async def storage_sts(
    workspace_id: str,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> dict[str, object]:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)
    if not pilot_storage_ready(settings):
        return _failure("DJI Pilot storage STS is not configured")

    try:
        credentials = await asyncio.to_thread(
            issue_pilot_sts_credentials,
            settings,
            workspace_id=workspace_id,
        )
    except DJIPilotStorageError as exc:
        return _failure(str(exc))

    return _success(credentials.as_dji_response())


@router.post("/media/api/v1/workspaces/{workspace_id}/fast-upload")
async def fast_upload(
    workspace_id: str,
    body: FastUploadBody,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> dict[str, object]:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)

    async with session_factory() as session:
        existing = await session.scalar(
            select(MediaAsset.id)
            .where(MediaAsset.dji_fingerprint == body.fingerprint)
            .limit(1)
        )
    if existing is None:
        return _failure(f"{body.fingerprint} don't exist.")
    return _success()


@router.post("/media/api/v1/workspaces/{workspace_id}/files/tiny-fingerprints")
async def tiny_fingerprints(
    workspace_id: str,
    body: TinyFingerprintBody,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> dict[str, object]:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)

    requested = sorted({value for value in body.tiny_fingerprints if value})
    if not requested:
        return _success({"tiny_fingerprints": []})

    async with session_factory() as session:
        existing = (
            await session.scalars(
                select(MediaAsset.dji_tiny_fingerprint).where(
                    MediaAsset.dji_tiny_fingerprint.in_(requested)
                )
            )
        ).all()

    return _success(
        {
            "tiny_fingerprints": sorted(
                {value for value in existing if isinstance(value, str)}
            )
        }
    )


@router.post("/media/api/v1/workspaces/{workspace_id}/upload-callback")
async def upload_callback(
    workspace_id: str,
    body: UploadCallbackBody,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> dict[str, object]:
    _validate_workspace(workspace_id)
    _validate_token(x_auth_token)

    if body.result != 0:
        return _failure(f"Pilot 2 reported upload failure: {body.result}")
    if not pilot_object_key_allowed(workspace_id, body.object_key):
        return _failure("object_key is outside the DJI Pilot workspace prefix")

    bucket = settings.dji_pilot_storage_bucket.strip() or "m3-media"
    try:
        stored = await asyncio.to_thread(
            inspect_uploaded_object,
            settings,
            bucket=bucket,
            object_key=body.object_key,
        )
    except Exception as exc:
        return _failure(f"Uploaded object verification failed: {exc}")

    classification = classify_pilot_media(
        name=body.name,
        drone_model_key=body.ext.drone_model_key,
    )
    capture_time = normalized_capture_time(body.metadata.created_time)
    now = datetime.now(timezone.utc)
    extension = PurePosixPath(body.name).suffix.lower()

    async with session_factory() as session:
        asset = await session.scalar(
            select(MediaAsset).where(MediaAsset.dji_object_key == body.object_key)
        )
        if asset is None:
            asset = MediaAsset(
                relative_path=body.object_key,
                filename=body.name,
                extension=extension,
                size_bytes=stored.size_bytes,
                mtime_ns=stored.mtime_ns,
                sha256=stored.sha256,
                capture_time_utc=capture_time,
                capture_time_source="DJI_CLOUD_API",
                metadata_version=1,
                metadata_status="READY",
                metadata_error=None,
                gps_latitude=body.metadata.shoot_position.lat,
                gps_longitude=body.metadata.shoot_position.lng,
                gps_altitude_m=body.metadata.absolute_altitude,
                dji_absolute_altitude_m=body.metadata.absolute_altitude,
                dji_relative_altitude_m=body.metadata.relative_altitude,
                gimbal_yaw_deg=body.metadata.gimbal_yaw_degree,
                metadata_json={},
                platform=classification.platform,
                media_kind=classification.media_kind,
                capture_group=(
                    body.ext.file_group_id
                    or classification.capture_group
                ),
                storage_mode="S3",
                external_root=bucket,
                present=True,
                dji_fingerprint=body.fingerprint,
                dji_tiny_fingerprint=body.ext.tinny_fingerprint,
                dji_object_key=body.object_key,
                dji_source_sn=body.ext.sn,
                dji_file_group_id=body.ext.file_group_id,
                discovered_at=now,
                last_seen_at=now,
            )
            session.add(asset)
        else:
            asset.filename = body.name
            asset.extension = extension
            asset.size_bytes = stored.size_bytes
            asset.mtime_ns = stored.mtime_ns
            asset.sha256 = stored.sha256
            asset.capture_time_utc = capture_time
            asset.capture_time_source = "DJI_CLOUD_API"
            asset.metadata_status = "READY"
            asset.metadata_error = None
            asset.gps_latitude = body.metadata.shoot_position.lat
            asset.gps_longitude = body.metadata.shoot_position.lng
            asset.gps_altitude_m = body.metadata.absolute_altitude
            asset.dji_absolute_altitude_m = body.metadata.absolute_altitude
            asset.dji_relative_altitude_m = body.metadata.relative_altitude
            asset.gimbal_yaw_deg = body.metadata.gimbal_yaw_degree
            asset.platform = classification.platform
            asset.media_kind = classification.media_kind
            asset.capture_group = body.ext.file_group_id or classification.capture_group
            asset.present = True
            asset.dji_fingerprint = body.fingerprint
            asset.dji_tiny_fingerprint = body.ext.tinny_fingerprint
            asset.dji_source_sn = body.ext.sn
            asset.dji_file_group_id = body.ext.file_group_id
            asset.last_seen_at = now

        asset.metadata_json = dji_metadata_json(
            fingerprint=body.fingerprint,
            tiny_fingerprint=body.ext.tinny_fingerprint,
            object_key=body.object_key,
            drone_model_key=body.ext.drone_model_key,
            payload_model_key=body.ext.payload_model_key,
            source_sn=body.ext.sn,
            file_group_id=body.ext.file_group_id,
            is_original=body.ext.is_original,
            sub_file_type=body.sub_file_type,
            path=body.path,
        )
        await session.commit()

    return _success({"object_key": body.object_key})
