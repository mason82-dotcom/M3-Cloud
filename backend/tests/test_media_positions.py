from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import delete

from app.api_media import media_positions
from app.database import session_factory
from app.models import MediaAsset


@pytest.mark.asyncio(loop_scope="session")
async def test_media_positions_returns_only_geotagged_originals() -> None:
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        await session.execute(delete(MediaAsset))
        session.add_all(
            [
                MediaAsset(
                    id=uuid.uuid4(),
                    relative_path="M3E/site/DJI_A_W.JPG",
                    filename="DJI_A_W.JPG",
                    extension=".jpg",
                    size_bytes=10,
                    mtime_ns=1,
                    sha256="a" * 64,
                    capture_time_utc=now,
                    capture_time_source="EXIF_DATETIME_ORIGINAL_OFFSET",
                    metadata_version=1,
                    metadata_status="READY",
                    metadata_json={},
                    platform="M3E",
                    media_kind="WIDE",
                    capture_group="M3E/site/DJI_A",
                    storage_mode="EXTERNAL",
                    external_root="media-import",
                    present=True,
                    duplicate_of=None,
                    discovered_at=now,
                    last_seen_at=now,
                    gps_latitude=49.1,
                    gps_longitude=8.5,
                    gps_altitude_m=130.0,
                    gps_altitude_ref="ABOVE_SEA_LEVEL",
                    dji_absolute_altitude_m=148.5,
                    dji_relative_altitude_m=32.0,
                ),
                MediaAsset(
                    id=uuid.uuid4(),
                    relative_path="M3E/site/DJI_B_W.JPG",
                    filename="DJI_B_W.JPG",
                    extension=".jpg",
                    size_bytes=10,
                    mtime_ns=2,
                    sha256="b" * 64,
                    metadata_version=1,
                    metadata_status="NO_METADATA",
                    metadata_json={},
                    platform="M3E",
                    media_kind="WIDE",
                    capture_group="M3E/site/DJI_B",
                    storage_mode="EXTERNAL",
                    external_root="media-import",
                    present=True,
                    duplicate_of=None,
                    discovered_at=now,
                    last_seen_at=now,
                ),
            ]
        )
        await session.commit()

    result = await media_positions(platform="M3E", limit=100)

    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 1
    feature = result["features"][0]
    assert feature["geometry"]["coordinates"] == [8.5, 49.1]
    assert feature["properties"]["dji_absolute_altitude_m"] == 148.5
    assert feature["properties"]["dji_relative_altitude_m"] == 32.0
