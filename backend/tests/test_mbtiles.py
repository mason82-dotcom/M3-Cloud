import sqlite3
import uuid
from pathlib import Path

from app.processing.mbtiles import publish_mbtiles


class Storage:
    def __init__(self):
        self.objects = {}

    def upload_fileobj(self, handle, bucket, key, ExtraArgs=None):
        self.objects[(bucket, key)] = {
            "data": handle.read(),
            "extra": ExtraArgs or {},
        }


def create_mbtiles(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        connection.execute(
            "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
        )
        connection.executemany(
            "INSERT INTO metadata(name, value) VALUES (?, ?)",
            [
                ("name", "test ortho"),
                ("format", "png"),
                ("bounds", "8.0,49.0,8.1,49.1"),
                ("minzoom", "1"),
                ("maxzoom", "1"),
            ],
        )
        connection.execute(
            "INSERT INTO tiles VALUES (?, ?, ?, ?)",
            (1, 0, 1, b"\x89PNG\r\n\x1a\nmock"),
        )
        connection.commit()
    finally:
        connection.close()


def test_mbtiles_publish_converts_tms_row_to_xyz(tmp_path: Path) -> None:
    path = tmp_path / "orthophoto.mbtiles"
    create_mbtiles(path)
    storage = Storage()
    job_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

    details = publish_mbtiles(
        storage,
        bucket="m3-results",
        job_id=job_id,
        mbtiles_path=path,
    )

    assert details["map_kind"] == "RASTER_XYZ"
    assert details["bounds"] == [8.0, 49.0, 8.1, 49.1]
    assert details["minzoom"] == 1
    assert details["maxzoom"] == 1
    assert details["tile_count"] == 1

    # TMS row 1 at z1 becomes XYZ row 0.
    key = (
        "m3-results",
        "webodm/11111111-1111-1111-1111-111111111111/"
        "orthophoto/tiles/1/0/0.png",
    )
    assert key in storage.objects
    assert storage.objects[key]["extra"]["ContentType"] == "image/png"
