from __future__ import annotations

import re
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

from botocore.client import BaseClient


RASTER_TILE_ARCHIVES = {
    "dsm_tiles.zip": "DSM",
    "dtm_tiles.zip": "DTM",
}

_TILE_RE = re.compile(
    r"^(?P<z>\d+)/(?P<x>\d+)/(?P<y>\d+)\.(?P<ext>png|jpg|jpeg|webp)$",
    re.IGNORECASE,
)


def _safe_path(raw: str) -> PurePosixPath:
    value = raw.replace("\\", "/").strip("/")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe raster tile archive path: {raw}")
    return path


def _content_type(extension: str) -> str:
    value = extension.lower()
    if value in {"jpg", "jpeg"}:
        return "image/jpeg"
    if value == "webp":
        return "image/webp"
    return "image/png"


def _metadata(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        raw = archive.read("tilemapresource.xml")
    except KeyError as exc:
        raise ValueError("tile archive does not contain tilemapresource.xml") from exc

    root = ElementTree.fromstring(raw)
    bounds_node = root.find("BoundingBox")
    bounds = None
    if bounds_node is not None:
        try:
            bounds = [
                float(bounds_node.attrib["minx"]),
                float(bounds_node.attrib["miny"]),
                float(bounds_node.attrib["maxx"]),
                float(bounds_node.attrib["maxy"]),
            ]
        except (KeyError, ValueError):
            bounds = None

    orders: list[int] = []
    tile_sets = root.find("TileSets")
    if tile_sets is not None:
        for node in tile_sets.findall("TileSet"):
            try:
                orders.append(int(node.attrib["order"]))
            except (KeyError, ValueError):
                continue

    tile_format = root.find("TileFormat")
    extension = (
        tile_format.attrib.get("extension", "png")
        if tile_format is not None
        else "png"
    ).lower()

    return {
        "bounds": bounds,
        "minzoom": min(orders) if orders else None,
        "maxzoom": max(orders) if orders else None,
        "extension": extension,
    }


def publish_raster_tiles(
    storage: BaseClient,
    *,
    bucket: str,
    job_id: uuid.UUID,
    asset_name: str,
    archive_path: Path,
) -> dict[str, Any]:
    """Publish ODM TMS tile ZIPs to MinIO as MapLibre-compatible XYZ tiles."""

    layer_type = RASTER_TILE_ARCHIVES.get(asset_name)
    if layer_type is None:
        raise ValueError(f"unsupported raster tile asset: {asset_name}")

    prefix = f"webodm/{job_id}/raster/{layer_type.lower()}/tiles"
    tile_count = 0
    found_zooms: list[int] = []
    extensions: set[str] = set()
    metadata: dict[str, Any]

    with zipfile.ZipFile(archive_path, "r") as archive:
        metadata = _metadata(archive)

        normalized: set[str] = set()
        for info in archive.infolist():
            if info.is_dir():
                continue

            path = _safe_path(info.filename)
            value = path.as_posix()
            if value in normalized:
                raise ValueError(f"duplicate raster tile archive path: {value}")
            normalized.add(value)

            match = _TILE_RE.fullmatch(value)
            if match is None:
                continue

            zoom = int(match.group("z"))
            column = int(match.group("x"))
            tms_row = int(match.group("y"))
            extension = match.group("ext").lower()
            if extension == "jpeg":
                extension = "jpg"

            max_index = (1 << zoom) - 1
            if column < 0 or column > max_index or tms_row < 0 or tms_row > max_index:
                raise ValueError(f"invalid TMS tile coordinate: {value}")

            xyz_row = max_index - tms_row
            object_key = f"{prefix}/{zoom}/{column}/{xyz_row}.{extension}"
            content_type = _content_type(extension)

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

            found_zooms.append(zoom)
            extensions.add(extension)
            tile_count += 1

    if tile_count == 0:
        raise ValueError(f"{asset_name} contains no raster tiles")
    if len(extensions) != 1:
        raise ValueError(f"{asset_name} mixes tile image formats")

    extension = next(iter(extensions))
    return {
        "map_kind": "RASTER_XYZ",
        "layer_type": layer_type,
        "tile_prefix": prefix,
        "tile_extension": extension,
        "tile_content_type": _content_type(extension),
        "tile_count": tile_count,
        "bounds": metadata.get("bounds"),
        "minzoom": metadata.get("minzoom") if metadata.get("minzoom") is not None else min(found_zooms),
        "maxzoom": metadata.get("maxzoom") if metadata.get("maxzoom") is not None else max(found_zooms),
        "source_scheme": "TMS",
        "published_scheme": "XYZ",
    }
