from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.database import session_factory
from app.models import (
    MediaAsset,
    MediaDatasetRecord,
    ProcessingJob,
    ProcessingJobAsset,
    ProcessingResult,
)
from app.processing.service import ProcessingManager


@pytest.mark.asyncio(loop_scope="session")
async def test_thermogram_job_freezes_required_input_metadata(tmp_path: Path) -> None:
    async with session_factory() as session:
        await session.execute(delete(ProcessingResult))
        await session.execute(delete(ProcessingJobAsset))
        await session.execute(delete(ProcessingJob))
        await session.execute(delete(MediaDatasetRecord))
        await session.execute(delete(MediaAsset))
        await session.commit()

    captured = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    group = "M3T/site/DJI_20260920120000_0001"

    async with session_factory() as session:
        wide = MediaAsset(
            relative_path=f"{group}_W.JPG",
            filename="DJI_20260920120000_0001_W.JPG",
            extension=".jpg",
            size_bytes=4,
            mtime_ns=1,
            sha256="a" * 64,
            capture_time_utc=captured,
            platform="M3T",
            media_kind="WIDE",
            capture_group=group,
            storage_mode="EXTERNAL",
            external_root="media-import",
            present=True,
            duplicate_of=None,
            discovered_at=now,
            last_seen_at=now,
        )
        thermal = MediaAsset(
            relative_path=f"{group}_T.JPG",
            filename="DJI_20260920120000_0001_T.JPG",
            extension=".jpg",
            size_bytes=7,
            mtime_ns=2,
            sha256="b" * 64,
            capture_time_utc=captured,
            platform="M3T",
            media_kind="THERMAL",
            capture_group=group,
            storage_mode="EXTERNAL",
            external_root="media-import",
            present=True,
            duplicate_of=None,
            discovered_at=now,
            last_seen_at=now,
        )
        session.add_all([wide, thermal])
        session.add(
            MediaDatasetRecord(
                prefix="M3T/site",
                platform="M3T",
                flight_id=None,
                title=None,
                capture_started_at=captured,
                capture_ended_at=captured,
                flight_assignment_source="AUTO",
                flight_match_status="NO_MATCH",
                flight_match_candidates=[],
                present=True,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    manager = ProcessingManager(
        session_factory,
        media_root=str(tmp_path),
        media_handoff_root=str(tmp_path),
        external_result_root=str(tmp_path / "results"),
        webodm_enabled=False,
        webodm_url="",
    )
    job = await manager.create_thermogram_job(
        name="M3T site",
        input_prefix="M3T/site",
    )

    async with session_factory() as session:
        snapshots = (
            await session.scalars(
                select(ProcessingJobAsset)
                .where(ProcessingJobAsset.job_id == job.id)
                .order_by(ProcessingJobAsset.ordinal)
            )
        ).all()

    assert len(snapshots) == 2
    assert [item.media_kind for item in snapshots] == ["WIDE", "THERMAL"]
    assert [item.relative_path for item in snapshots] == [
        f"{group}_W.JPG",
        f"{group}_T.JPG",
    ]
    assert [item.size_bytes for item in snapshots] == [4, 7]
    assert [item.sha256 for item in snapshots] == ["a" * 64, "b" * 64]
    assert [item.capture_group for item in snapshots] == [group, group]
    assert [item.capture_time_utc for item in snapshots] == [captured, captured]
