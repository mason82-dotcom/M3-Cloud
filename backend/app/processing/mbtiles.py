from __future__ import annotations

import io
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from botocore.client import BaseClient


def _tile_format(data: bytes, declared: str | None) -> tuple[str, str]:
    value = (declared or "").strip().lower()
    if value in {"jpg", "jpeg"} or data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if value == "webp" or data.startswith(b"RIFF"):
        return "webp", "image/webp"
    return "png", "image/png"


def publish_mbtiles(
    storage: BaseClient,
    *,
    bucket: str,
    job_id: uuid.UUID,
    mbtiles_path: Path,
) -> dict[str, Any]:
    """Publish MBTiles to MinIO as XYZ tiles and return map metadata."""

    connection = sqlite3.connect(f"file:{mbtiles_path}?mode=ro", uri=True)
    try:
        metadata = {
            str(name): str(value)
            for name, value in connection.execute("SELECT name, value FROM metadata")
        }
        bounds = None
        raw_bounds = metadata.get("bounds")
        if raw_bounds:
            values = [float(value) for value in raw_bounds.split(",")]
            if len(values) == 4:
                bounds = values

        declared_format = metadata.get("format")
        minzoom = int(metadata["minzoom"]) if metadata.get("minzoom") else None
        maxzoom = int(metadata["maxzoom"]) if metadata.get("maxzoom") else None

        prefix = f"webodm/{job_id}/orthophoto/tiles"
        tile_count = 0
        tile_extension = "png"
        tile_content_type = "image/png"

        cursor = connection.execute(
            """
            SELECT zoom_level, tile_column, tile_row, tile_data
            FROM tiles
            ORDER BY zoom_level, tile_column, tile_row
            """
        )
        for zoom, column, tms_row, tile_data in cursor:
            data = bytes(tile_data)
            extension, content_type = _tile_format(data, declared_format)
            tile_extension = extension
            tile_content_type = content_type
            xyz_row = (1 << int(zoom)) - 1 - int(tms_row)
            object_key = (
                f"{prefix}/{int(zoom)}/{int(column)}/{xyz_row}.{extension}"
            )
            storage.upload_fileobj(
                io.BytesIO(data),
                bucket,
                object_key,
                ExtraArgs={
                    "ContentType": content_type,
                    "CacheControl": "public, max-age=31536000, immutable",
                },
            )
            tile_count += 1

        if tile_count == 0:
            raise ValueError("orthophoto.mbtiles contains no tiles")

        return {
            "map_kind": "RASTER_XYZ",
            "tile_prefix": prefix,
            "tile_extension": tile_extension,
            "tile_content_type": tile_content_type,
            "tile_count": tile_count,
            "bounds": bounds,
            "minzoom": minzoom,
            "maxzoom": maxzoom,
            "name": metadata.get("name"),
            "description": metadata.get("description"),
            "attribution": metadata.get("attribution"),
        }
    finally:
        connection.close()
