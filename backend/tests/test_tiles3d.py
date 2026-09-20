import io
import json
import math
import uuid
import zipfile
from pathlib import Path

import pytest

from app.processing.tiles3d import publish_3d_tiles


class Storage:
    def __init__(self):
        self.objects = {}

    def upload_fileobj(self, handle, bucket, key, ExtraArgs=None):
        self.objects[(bucket, key)] = {
            "data": handle.read(),
            "extra": ExtraArgs or {},
        }


def make_archive(path: Path, *, unsafe: bool = False) -> None:
    region = [
        math.radians(8.0),
        math.radians(49.0),
        math.radians(8.1),
        math.radians(49.1),
        100.0,
        160.0,
    ]
    tileset = {
        "asset": {"version": "1.1"},
        "geometricError": 100,
        "root": {
            "boundingVolume": {"region": region},
            "geometricError": 0,
            "content": {"uri": "tiles/0.b3dm"},
        },
    }

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("scene/tileset.json", json.dumps(tileset))
        archive.writestr("scene/tiles/0.b3dm", b"b3dm-mock")
        if unsafe:
            archive.writestr("../escape.bin", b"bad")


def test_publish_3d_tiles_preserves_tree_and_bounds(tmp_path: Path) -> None:
    path = tmp_path / "3d_tiles_model.zip"
    make_archive(path)
    storage = Storage()
    job_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

    details = publish_3d_tiles(
        storage,
        bucket="m3-results",
        job_id=job_id,
        asset_name="3d_tiles_model.zip",
        archive_path=path,
    )

    assert details["scene_kind"] == "3D_TILES"
    assert details["scene_type"] == "MODEL"
    assert details["tileset_path"] == "scene/tileset.json"
    assert details["file_count"] == 2
    assert details["bounds"] == pytest.approx([8.0, 49.0, 8.1, 49.1])
    assert details["asset_version"] == "1.1"

    prefix = "webodm/11111111-1111-1111-1111-111111111111/3d/model"
    assert ("m3-results", f"{prefix}/scene/tileset.json") in storage.objects
    assert ("m3-results", f"{prefix}/scene/tiles/0.b3dm") in storage.objects


def test_publish_3d_tiles_rejects_zip_slip(tmp_path: Path) -> None:
    path = tmp_path / "3d_tiles_model.zip"
    make_archive(path, unsafe=True)

    with pytest.raises(ValueError, match="unsafe 3D Tiles archive path"):
        publish_3d_tiles(
            Storage(),
            bucket="m3-results",
            job_id=uuid.uuid4(),
            asset_name="3d_tiles_model.zip",
            archive_path=path,
        )
