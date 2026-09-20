from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.database import session_factory
from app.media.importer import MediaImporter
from app.models import Flight, MediaAsset, MediaDatasetRecord


@pytest.mark.asyncio(loop_scope="session")
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



@pytest.mark.asyncio(loop_scope="session")
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



@pytest.mark.asyncio(loop_scope="session")
async def test_recent_visible_file_is_not_marked_missing(tmp_path: Path) -> None:
    async with session_factory() as session:
        await session.execute(delete(MediaAsset))
        await session.commit()

    root = tmp_path / "media"
    path = root / "M3E" / "flight" / "DJI_0001_W.JPG"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"stable")

    initial = MediaImporter(
        session_factory,
        root=str(root),
        min_age_seconds=0,
    )
    await initial.scan()

    path.write_bytes(b"copy still in progress")

    guarded = MediaImporter(
        session_factory,
        root=str(root),
        min_age_seconds=3600,
    )
    result = await guarded.scan()

    assert result.scanned == 0
    assert result.skipped_unstable == 1
    assert result.marked_missing == 0

    async with session_factory() as session:
        asset = await session.scalar(
            select(MediaAsset).where(
                MediaAsset.relative_path == "M3E/flight/DJI_0001_W.JPG"
            )
        )
    assert asset is not None
    assert asset.present is True



@pytest.mark.asyncio(loop_scope="session")
async def test_present_duplicate_is_promoted_when_original_disappears(tmp_path: Path) -> None:
    async with session_factory() as session:
        await session.execute(delete(MediaAsset))
        await session.commit()

    root = tmp_path / "media"
    original = root / "M3E" / "site" / "DJI_0001_W.JPG"
    copy = root / "backup" / "DJI_0001_W.JPG"
    original.parent.mkdir(parents=True)
    copy.parent.mkdir(parents=True)
    original.write_bytes(b"same-original-bytes")
    copy.write_bytes(b"same-original-bytes")

    importer = MediaImporter(session_factory, root=str(root), min_age_seconds=0)
    await importer.scan()

    async with session_factory() as session:
        initial = (
            await session.scalars(
                select(MediaAsset).where(MediaAsset.present.is_(True))
            )
        ).all()
    assert sum(asset.duplicate_of is None for asset in initial) == 1
    assert sum(asset.duplicate_of is not None for asset in initial) == 1

    canonical = next(asset for asset in initial if asset.duplicate_of is None)
    (root / canonical.relative_path).unlink()

    result = await importer.scan()
    assert result.marked_missing == 1
    assert result.duplicates == 0

    async with session_factory() as session:
        remaining = await session.scalar(
            select(MediaAsset).where(MediaAsset.present.is_(True))
        )
    assert remaining is not None
    assert remaining.duplicate_of is None



@pytest.mark.asyncio(loop_scope="session")
async def test_media_dataset_assignment_survives_rescan(tmp_path: Path) -> None:
    async with session_factory() as session:
        await session.execute(delete(MediaDatasetRecord))
        await session.execute(delete(MediaAsset))
        await session.execute(delete(Flight))
        await session.commit()

    root = tmp_path / "media"
    folder = root / "M3E" / "survey"
    folder.mkdir(parents=True)
    (folder / "DJI_0001_W.JPG").write_bytes(b"image-1")
    (folder / "DJI_0002_W.JPG").write_bytes(b"image-2")

    importer = MediaImporter(session_factory, root=str(root), min_age_seconds=0)
    await importer.scan()

    async with session_factory() as session:
        dataset = await session.scalar(
            select(MediaDatasetRecord).where(
                MediaDatasetRecord.platform == "M3E",
                MediaDatasetRecord.prefix == "M3E/survey",
            )
        )
        assert dataset is not None

        flight = Flight(
            aircraft_sn="M3E-TEST",
            status="COMPLETED",
            started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            distance_m=0.0,
            rtk_converged_samples=0,
            rtk_total_samples=0,
        )
        session.add(flight)
        await session.flush()
        dataset.flight_id = flight.id
        await session.commit()
        dataset_id = dataset.id
        flight_id = flight.id

    await importer.scan()

    async with session_factory() as session:
        dataset = await session.get(MediaDatasetRecord, dataset_id)
        assert dataset is not None
        assert dataset.present is True
        assert dataset.flight_id == flight_id
