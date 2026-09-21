from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from app.config import Settings
from app.dji.storage_sts import create_pilot_storage_client
from app.media.classifier import MediaClassification, classify_media


_MODEL_PLATFORM = {
    "0-77-0": "M3E",
    "0-77-1": "M3T",
    "0-77-2": "M3M",
}


@dataclass(frozen=True)
class StoredObjectInfo:
    size_bytes: int
    mtime_ns: int
    sha256: str


def platform_from_model_key(value: str) -> str:
    return _MODEL_PLATFORM.get(value, "UNKNOWN")


def classify_pilot_media(
    *,
    name: str,
    drone_model_key: str,
) -> MediaClassification:
    platform = platform_from_model_key(drone_model_key)
    path = (
        PurePosixPath(platform, name)
        if platform != "UNKNOWN"
        else PurePosixPath(name)
    )
    classified = classify_media(path)
    if classified.platform == "UNKNOWN" and platform != "UNKNOWN":
        return MediaClassification(
            platform=platform,
            media_kind=classified.media_kind,
            capture_group=classified.capture_group,
        )
    return classified


def normalized_capture_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def inspect_uploaded_object(
    settings: Settings,
    *,
    bucket: str,
    object_key: str,
) -> StoredObjectInfo:
    client = create_pilot_storage_client(settings)
    head = client.head_object(Bucket=bucket, Key=object_key)
    size_bytes = int(head.get("ContentLength") or 0)
    last_modified = head.get("LastModified")
    if isinstance(last_modified, datetime):
        mtime_ns = int(last_modified.timestamp() * 1_000_000_000)
    else:
        mtime_ns = 0

    response = client.get_object(Bucket=bucket, Key=object_key)
    body = response["Body"]
    digest = hashlib.sha256()
    try:
        for chunk in iter(lambda: body.read(1024 * 1024), b""):
            digest.update(chunk)
    finally:
        body.close()

    return StoredObjectInfo(
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        sha256=digest.hexdigest(),
    )


def dji_metadata_json(
    *,
    fingerprint: str,
    tiny_fingerprint: str,
    object_key: str,
    drone_model_key: str,
    payload_model_key: str,
    source_sn: str,
    file_group_id: str | None,
    is_original: bool,
    sub_file_type: int,
    path: str | None,
) -> dict[str, Any]:
    return {
        "dji_cloud_api": {
            "fingerprint": fingerprint,
            "tiny_fingerprint": tiny_fingerprint,
            "object_key": object_key,
            "drone_model_key": drone_model_key,
            "payload_model_key": payload_model_key,
            "source_sn": source_sn,
            "file_group_id": file_group_id,
            "is_original": is_original,
            "sub_file_type": sub_file_type,
            "path": path,
        }
    }
