import uuid
import zipfile
from pathlib import Path

import pytest

from app.processing.rastertiles import publish_raster_tiles


class Storage:
    def __init__(self):
        self.objects = {}

    def upload_fileobj(self, handle, bucket, key, ExtraArgs=None):
        self.objects[(bucket, key)] = {
            "data": handle.read(),
            "extra": ExtraArgs or {},
        }


def make_tiles(path: Path, *, unsafe: bool = False) -> None:
    metadata = """<?xml version="1.0" encoding="utf-8"?>
<TileMap version="1.0.0" tilemapservice="http://tms.osgeo.org/1.0.0">
  <Title>DSM</Title>
  <Abstract></Abstract>
  <SRS>EPSG:3857</SRS>
  <BoundingBox minx="8.0" miny="49.0" maxx="8.1" maxy="49.1"/>
  <Origin x="8.0" y="49.0"/>
  <TileFormat width="256" height="256" mime-type="image/png" extension="png"/>
  <TileSets profile="mercator">
    <TileSet href="5" units-per-pixel="4891" order="5"/>
    <TileSet href="6" units-per-pixel="2445" order="6"/>
  </TileSets>
</TileMap>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("tilemapresource.xml", metadata)
        archive.writestr("6/32/20.png", b"png-tile")
        if unsafe:
            archive.writestr("../escape.png", b"bad")


def test_publish_dsm_tms_as_xyz(tmp_path: Path) -> None:
    archive = tmp_path / "dsm_tiles.zip"
    make_tiles(archive)
    storage = Storage()
    job_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

    details = publish_raster_tiles(
        storage,
        bucket="m3-results",
        job_id=job_id,
        asset_name="dsm_tiles.zip",
        archive_path=archive,
    )

    assert details["layer_type"] == "DSM"
    assert details["bounds"] == [8.0, 49.0, 8.1, 49.1]
    assert details["minzoom"] == 5
    assert details["maxzoom"] == 6
    assert details["source_scheme"] == "TMS"
    assert details["published_scheme"] == "XYZ"

    # z6 max y=63, so TMS row 20 is XYZ row 43.
    key = (
        "m3-results",
        "webodm/11111111-1111-1111-1111-111111111111/raster/dsm/"
        "tiles/6/32/43.png",
    )
    assert key in storage.objects
    assert storage.objects[key]["data"] == b"png-tile"


def test_publish_raster_tiles_rejects_zip_slip(tmp_path: Path) -> None:
    archive = tmp_path / "dtm_tiles.zip"
    make_tiles(archive, unsafe=True)

    with pytest.raises(ValueError, match="unsafe raster tile archive path"):
        publish_raster_tiles(
            Storage(),
            bucket="m3-results",
            job_id=uuid.uuid4(),
            asset_name="dtm_tiles.zip",
            archive_path=archive,
        )
