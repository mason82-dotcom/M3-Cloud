from __future__ import annotations

import json
import math
import mimetypes
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from botocore.client import BaseClient


THREE_D_TILE_ARCHIVES = {
    "3d_tiles_model.zip": "model",
    "3d_tiles_pointcloud.zip": "pointcloud",
}


def _safe_archive_path(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe 3D Tiles archive path: {name}")
    return path


def _content_type(path: PurePosixPath) -> str:
    suffix = path.suffix.lower()
    special = {
        ".json": "application/json",
        ".glb": "model/gltf-binary",
        ".gltf": "model/gltf+json",
        ".b3dm": "application/octet-stream",
        ".pnts": "application/octet-stream",
        ".i3dm": "application/octet-stream",
        ".cmpt": "application/octet-stream",
    }
    return special.get(
        suffix,
        mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )


def _region_bounds(tileset: dict[str, Any]) -> list[float] | None:
    root = tileset.get("root")
    if not isinstance(root, dict):
        return None
    volume = root.get("boundingVolume")
    if not isinstance(volume, dict):
        return None
    region = volume.get("region")
    if not isinstance(region, list) or len(region) != 6:
        return None
    if not all(isinstance(value, (int, float)) for value in region):
        return None

    west, south, east, north = [float(value) for value in region[:4]]
    if not all(math.isfinite(value) for value in (west, south, east, north)):
        return None
    return [
        math.degrees(west),
        math.degrees(south),
        math.degrees(east),
        math.degrees(north),
    ]


def publish_3d_tiles(
    storage: BaseClient,
    *,
    bucket: str,
    job_id: uuid.UUID,
    asset_name: str,
    archive_path: Path,
) -> dict[str, Any]:
    """Publish a WebODM 3D Tiles ZIP to MinIO without rewriting its contents."""

    scene_kind = THREE_D_TILE_ARCHIVES.get(asset_name)
    if scene_kind is None:
        raise ValueError(f"unsupported 3D Tiles asset: {asset_name}")

    prefix = f"webodm/{job_id}/3d/{scene_kind}"
    tileset_candidates: list[PurePosixPath] = []
    file_count = 0
    total_bytes = 0
    tileset_json: dict[str, Any] | None = None

    with zipfile.ZipFile(archive_path, "r") as archive:
        entries: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
        for info in archive.infolist():
            if info.is_dir():
                continue
            path = _safe_archive_path(info.filename)
            entries.append((info, path))
            if path.name.lower() == "tileset.json":
                tileset_candidates.append(path)

        if not tileset_candidates:
            raise ValueError(f"{asset_name} does not contain tileset.json")

        tileset_path = min(tileset_candidates, key=lambda item: (len(item.parts), item.as_posix()))

        with archive.open(tileset_path.as_posix()) as handle:
            raw = handle.read()
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("tileset.json must contain a JSON object")
            tileset_json = parsed

        for info, path in entries:
            object_key = f"{prefix}/{path.as_posix()}"
            content_type = _content_type(path)
            with archive.open(info) as handle:
                storage.upload_fileobj(
                    handle,
                    bucket,
                    object_key,
                    ExtraArgs={
                        "ContentType": content_type,
                        "CacheControl": "public, max-age=31536000, immutable",
                    },
                )
            file_count += 1
            total_bytes += int(info.file_size)

    return {
        "scene_kind": "3D_TILES",
        "scene_type": scene_kind.upper(),
        "scene_prefix": prefix,
        "tileset_path": tileset_path.as_posix(),
        "file_count": file_count,
        "published_bytes": total_bytes,
        "bounds": _region_bounds(tileset_json or {}),
        "asset_version": (
            (tileset_json or {}).get("asset", {}).get("version")
            if isinstance((tileset_json or {}).get("asset"), dict)
            else None
        ),
    }
