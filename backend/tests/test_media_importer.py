from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.database import session_factory
from app.media.importer import MediaImporter
from app.models import MediaAsset


@pytest.mark.asyncio
async def test_external_media_scan_catalogs_and_deduplicates(tmp_path: Path) -> None:
    async with session_factory() as session:
        await session.execute(delete(MediaAsset))
        await session.commit()

    root = tmp_path / "media"
    first = root / "M3M" / "flight" / "DJI_20221031174036_0001_D.JPG"
    band = root / "M3M" / "flight" / "DJI_20221031174036_0001_MS_NIR.TIF"
    duplicate = root / "copy" / "DJI_20221031174036_0001_D.JPG"

    first.parent.mkdir(parents=True)
    duplicate.parent.mkdir(parents=True)
    first.write_bytes(b"rgb-original")
    band.write_bytes(b"nir-original")
    duplicate.write_bytes(b"rgb-original")

    importer = MediaImporter(
        session_factory,
        root=str(root),
        min_age_seconds=0,
    )
    result = await importer.scan()

    assert result.scanned == 3
    assert result.added == 2
    assert result.duplicates == 1

    async with session_factory() as session:
        assets = (await session.scalars(select(MediaAsset).order_by(MediaAsset.relative_path))).all()

    assert len(assets) == 3
    rgb = next(asset for asset in assets if asset.relative_path.startswith("M3M/") and asset.media_kind == "RGB")
    nir = next(asset for asset in assets if asset.media_kind == "MS_NIR")
    copied = next(asset for asset in assets if asset.relative_path.startswith("copy/"))

    assert rgb.platform == "M3M"
    assert nir.platform == "M3M"
    assert rgb.capture_group == "M3M/flight/DJI_20221031174036_0001"
    assert nir.capture_group == rgb.capture_group
    assert copied.duplicate_of == rgb.id
    assert copied.storage_mode == "EXTERNAL"

    second = await importer.scan()
    assert second.unchanged == 3

    band.unlink()
    third = await importer.scan()
    assert third.marked_missing == 1

    async with session_factory() as session:
        missing = await session.scalar(
            select(MediaAsset).where(MediaAsset.id == nir.id)
        )
    assert missing is not None
    assert missing.present is False



@pytest.mark.asyncio
async def test_missing_import_root_does_not_mark_catalog_missing(tmp_path: Path) -> None:
    async with session_factory() as session:
        await session.execute(delete(MediaAsset))
        session.add(
            MediaAsset(
                relative_path="M3E/existing.JPG",
                filename="existing.JPG",
                extension=".jpg",
                size_bytes=123,
                mtime_ns=1,
                sha256="a" * 64,
                platform="M3E",
                media_kind="RGB",
                capture_group="M3E/existing",
                storage_mode="EXTERNAL",
                external_root="media-import",
                present=True,
                duplicate_of=None,
                discovered_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                last_seen_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            )
        )
        await session.commit()

    importer = MediaImporter(
        session_factory,
        root=str(tmp_path / "not-mounted"),
        min_age_seconds=0,
    )
    result = await importer.scan()

    assert result.marked_missing == 0
    assert importer.last_error == "IMPORT_ROOT_UNAVAILABLE"

    async with session_factory() as session:
        asset = await session.scalar(
            select(MediaAsset).where(MediaAsset.relative_path == "M3E/existing.JPG")
        )
    assert asset is not None
    assert asset.present is True
