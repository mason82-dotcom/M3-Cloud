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
            capture_time_source="XMP_DJI_UTC_AT_EXPOSURE",
            metadata_version=2,
            metadata_status="READY",
            camera_make="DJI",
            camera_model="M3T",
            image_width=5280,
            image_height=3956,
            gps_latitude=49.1234,
            gps_longitude=8.5678,
            gimbal_yaw_deg=12.0,
            gimbal_pitch_deg=-90.0,
            gimbal_roll_deg=0.0,
            metadata_json={
                "version": 2,
                "xmp": {
                    "drone-dji": {
                        "DroneModel": "M3T",
                        "UTCAtExposure": "2026-09-20T10:00:00.000000",
                    }
                },
            },
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
            capture_time_source="XMP_DJI_UTC_AT_EXPOSURE",
            metadata_version=2,
            metadata_status="READY",
            camera_make="DJI",
            camera_model="M3T",
            image_width=640,
            image_height=512,
            focal_length_mm=9.1,
            focal_length_35mm=40.0,
            gps_latitude=49.1234,
            gps_longitude=8.5678,
            gps_altitude_m=145.2,
            dji_absolute_altitude_m=145.7,
            dji_relative_altitude_m=60.2,
            flight_yaw_deg=11.5,
            flight_pitch_deg=1.0,
            flight_roll_deg=-0.5,
            gimbal_yaw_deg=12.0,
            gimbal_pitch_deg=-90.0,
            gimbal_roll_deg=0.0,
            metadata_json={
                "version": 2,
                "xmp": {
                    "drone-dji": {
                        "DroneModel": "M3T",
                        "UTCAtExposure": "2026-09-20T10:00:00.000000",
                        "CalibratedFocalLength": "9100.000000",
                    }
                },
            },
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
    assert snapshots[0].metadata_snapshot["camera"]["model"] == "M3T"
    assert snapshots[1].metadata_snapshot["camera"]["model"] == "M3T"
    assert snapshots[1].metadata_snapshot["gps"] == {
        "latitude": 49.1234,
        "longitude": 8.5678,
        "altitude_m": 145.2,
        "altitude_ref": None,
    }
    assert snapshots[1].metadata_snapshot["gimbal_attitude"] == {
        "yaw_deg": 12.0,
        "pitch_deg": -90.0,
        "roll_deg": 0.0,
    }
    assert snapshots[1].metadata_snapshot["raw"]["xmp"]["drone-dji"][
        "DroneModel"
    ] == "M3T"

    async with session_factory() as session:
        live_thermal = await session.scalar(
            select(MediaAsset).where(MediaAsset.media_kind == "THERMAL")
        )
        assert live_thermal is not None
        live_thermal.camera_model = "M30T"
        live_thermal.gps_latitude = 1.0
        live_thermal.gps_longitude = 2.0
        live_thermal.gimbal_pitch_deg = -45.0
        live_thermal.metadata_json = {
            "version": 2,
            "xmp": {"drone-dji": {"DroneModel": "M30T"}},
        }
        await session.commit()

    handoff = await manager.thermogram_handoff(job.id)
    thermal_file = next(
        item
        for item in handoff["capture_groups"][0]["files"]
        if item["media_kind"] == "THERMAL"
    )
    frozen_metadata = thermal_file["metadata"]
    assert frozen_metadata["camera"]["model"] == "M3T"
    assert frozen_metadata["gps"]["latitude"] == 49.1234
    assert frozen_metadata["gps"]["longitude"] == 8.5678
    assert frozen_metadata["gimbal_attitude"]["pitch_deg"] == -90.0
    assert frozen_metadata["raw"]["xmp"]["drone-dji"]["DroneModel"] == "M3T"
