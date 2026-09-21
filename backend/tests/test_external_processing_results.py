from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.database import session_factory
from app.models import ProcessingJob, ProcessingResult
from app.processing.service import ProcessingManager, thermal_result_manifest_details


class FakeStorage:
    def __init__(self):
        self.objects = {}

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.objects[(bucket, key)] = {
            "data": Path(filename).read_bytes(),
            "content_type": (ExtraArgs or {}).get("ContentType"),
        }


@pytest.mark.asyncio(loop_scope="session")
async def test_thermogram_external_results_are_archived(
    tmp_path: Path,
    monkeypatch,
) -> None:
    job_id = __import__("uuid").uuid4()
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        session.add(
            ProcessingJob(
                id=job_id,
                kind="THERMOGRAM",
                status="COMPLETED_EXTERNAL",
                name="M3T test",
                input_prefix="M3T/site-a",
                platform="M3T",
                flight_id=None,
                media_kinds=["WIDE", "THERMAL"],
                options=[],
                image_count=2,
                uploaded_count=0,
                progress=1.0,
                remote_project_id=None,
                remote_task_id=None,
                remote_status=None,
                available_assets=[],
                error=None,
                created_at=now,
                started_at=now,
                updated_at=now,
                finished_at=now,
            )
        )
        await session.commit()

    result_root = tmp_path / "processing-import"
    job_root = result_root / str(job_id)
    (job_root / "reports").mkdir(parents=True)
    (job_root / "reports" / "thermal.csv").write_bytes(b"spot,temp\nA,42.1\n")
    (job_root / "preview.png").write_bytes(b"png-bytes")

    storage = FakeStorage()
    monkeypatch.setattr(
        "app.processing.service.create_storage_client",
        lambda: storage,
    )

    manager = ProcessingManager(
        session_factory,
        media_root=str(tmp_path / "media"),
        external_result_root=str(result_root),
        external_result_handoff_root=r"\\m3-cloud\processing-import",
        webodm_enabled=False,
        webodm_url="",
    )

    status = await manager.external_result_status(job_id)
    assert status["file_count"] == 2
    assert status["drop_path"] == rf"\\m3-cloud\processing-import\{job_id}"

    results = await manager.import_external_results(job_id)
    assert [result.asset_name for result in results] == [
        "preview.png",
        "reports/thermal.csv",
    ]

    assert storage.objects[
        ("m3-results", f"external/{job_id}/preview.png")
    ]["data"] == b"png-bytes"
    assert storage.objects[
        ("m3-results", f"external/{job_id}/reports/thermal.csv")
    ]["data"] == b"spot,temp\nA,42.1\n"

    async with session_factory() as session:
        job = await session.get(ProcessingJob, job_id)
        stored = (
            await session.scalars(
                select(ProcessingResult)
                .where(ProcessingResult.job_id == job_id)
                .order_by(ProcessingResult.asset_name)
            )
        ).all()

    assert job is not None
    assert job.status == "COMPLETED"
    assert job.error is None
    assert job.available_assets == ["preview.png", "reports/thermal.csv"]
    assert len(stored) == 2
    assert all(result.details["source"] == "external" for result in stored)
    assert all(result.details["workflow"] == "THERMOGRAM" for result in stored)
    assert all(len(result.sha256) == 64 for result in stored)



def test_native_thermal_result_manifest_is_classified(tmp_path: Path) -> None:
    root = tmp_path / "thermal-results"
    capture = root / "captures" / "00001_DJI_0001_deadbeef00"
    capture.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "contract": "M3T_THERMAL_RESULTS_V1",
        "workflow": "THERMOGRAM",
        "platform": "M3T",
        "job_id": "job",
        "source_handoff_schema": 3,
        "input_fingerprint": "a" * 64,
        "capture_groups": [
            {
                "capture_group": "M3T/site/DJI_0001",
                "temperature_tif": (
                    "captures/00001_DJI_0001_deadbeef00/temperature.tif"
                ),
                "preview_png": "captures/00001_DJI_0001_deadbeef00/preview.png",
                "thermal_json": "captures/00001_DJI_0001_deadbeef00/thermal.json",
                "hotspot_mask_png": "captures/00001_DJI_0001_deadbeef00/hotspot-mask.png",
                "hotspots_json": "captures/00001_DJI_0001_deadbeef00/hotspots.json",
                "statistics": {"min_c": 20.0, "max_c": 42.5},
                "hotspots": {
                    "baseline_c": 22.0,
                    "threshold_c": 32.0,
                    "component_count": 1,
                    "candidate_pixels": 6,
                    "candidate_fraction": 0.001,
                },
                "width": 640,
                "height": 512,
                "sdk_label": "1.8_20251211",
                "api_version": {"api": 8, "magic": "DIRP"},
                "measurement_mode": "sdk_native",
                "measurement_ranges": {
                    "distance_m": {"min": 1.0, "max": 500.0},
                },
            }
        ],
    }
    (root / "result-manifest.json").write_text(
        __import__("json").dumps(manifest),
        encoding="utf-8",
    )

    details = thermal_result_manifest_details(root, expected_job_id="job")

    temperature = details[
        "captures/00001_DJI_0001_deadbeef00/temperature.tif"
    ]
    preview = details["captures/00001_DJI_0001_deadbeef00/preview.png"]
    metadata = details["captures/00001_DJI_0001_deadbeef00/thermal.json"]
    hotspot_mask = details[
        "captures/00001_DJI_0001_deadbeef00/hotspot-mask.png"
    ]
    hotspots = details[
        "captures/00001_DJI_0001_deadbeef00/hotspots.json"
    ]

    assert temperature["result_kind"] == "TEMPERATURE_RASTER"
    assert temperature["temperature_unit"] == "degree_Celsius"
    assert temperature["georeferenced"] is False
    assert temperature["statistics"]["max_c"] == 42.5
    assert temperature["sdk_label"] == "1.8_20251211"
    assert temperature["api_version"] == {"api": 8, "magic": "DIRP"}
    assert temperature["measurement_ranges"]["distance_m"]["max"] == 500.0
    assert temperature["input_fingerprint"] == "a" * 64
    assert preview["result_kind"] == "THERMAL_PREVIEW"
    assert metadata["result_kind"] == "THERMAL_METADATA"
    assert hotspot_mask["result_kind"] == "HOTSPOT_MASK"
    assert hotspots["result_kind"] == "HOTSPOT_ANALYSIS"
    assert hotspots["hotspots"]["component_count"] == 1
    assert details["result-manifest.json"]["result_kind"] == "THERMAL_MANIFEST"





def test_native_thermal_manifest_rejects_wrong_processing_job(tmp_path: Path) -> None:
    root = tmp_path / "thermal-results"
    root.mkdir()
    manifest = {
        "schema_version": 1,
        "contract": "M3T_THERMAL_RESULTS_V1",
        "workflow": "THERMOGRAM",
        "platform": "M3T",
        "job_id": "job-a",
        "capture_groups": [],
    }
    (root / "result-manifest.json").write_text(
        __import__("json").dumps(manifest),
        encoding="utf-8",
    )

    assert thermal_result_manifest_details(
        root,
        expected_job_id="job-b",
    ) == {}


@pytest.mark.asyncio(loop_scope="session")
async def test_external_status_retries_are_idempotent(tmp_path: Path) -> None:
    job_id = __import__("uuid").uuid4()
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        session.add(
            ProcessingJob(
                id=job_id,
                kind="THERMOGRAM",
                status="WAITING_EXTERNAL",
                name="M3T idempotency",
                input_prefix="M3T/idempotency",
                platform="M3T",
                flight_id=None,
                media_kinds=["WIDE", "THERMAL"],
                options=[],
                image_count=2,
                uploaded_count=0,
                progress=0.0,
                remote_project_id=None,
                remote_task_id=None,
                remote_status=None,
                available_assets=[],
                error=None,
                created_at=now,
                started_at=None,
                updated_at=now,
                finished_at=None,
            )
        )
        await session.commit()

    manager = ProcessingManager(
        session_factory,
        media_root=str(tmp_path / "media"),
        external_result_root=str(tmp_path / "processing-import"),
        webodm_enabled=False,
        webodm_url="",
    )

    running = await manager.update_external_job(
        job_id,
        new_status="RUNNING_EXTERNAL",
    )
    running_retry = await manager.update_external_job(
        job_id,
        new_status="RUNNING_EXTERNAL",
    )
    assert running.status == "RUNNING_EXTERNAL"
    assert running_retry.status == "RUNNING_EXTERNAL"

    completed = await manager.update_external_job(
        job_id,
        new_status="COMPLETED_EXTERNAL",
    )
    completed_retry = await manager.update_external_job(
        job_id,
        new_status="COMPLETED_EXTERNAL",
    )
    assert completed.status == "COMPLETED_EXTERNAL"
    assert completed_retry.status == "COMPLETED_EXTERNAL"

@pytest.mark.asyncio(loop_scope="session")
async def test_thermal_worker_claim_is_not_idempotent_for_competing_workers(
    tmp_path: Path,
) -> None:
    job_id = __import__("uuid").uuid4()
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        session.add(
            ProcessingJob(
                id=job_id,
                kind="THERMOGRAM",
                status="WAITING_EXTERNAL",
                name="M3T atomic claim",
                input_prefix="M3T/atomic-claim",
                platform="M3T",
                flight_id=None,
                media_kinds=["WIDE", "THERMAL"],
                options=[],
                image_count=2,
                uploaded_count=0,
                progress=0.0,
                remote_project_id=None,
                remote_task_id=None,
                remote_status=None,
                available_assets=[],
                error=None,
                created_at=now,
                started_at=None,
                updated_at=now,
                finished_at=None,
            )
        )
        await session.commit()

    manager = ProcessingManager(
        session_factory,
        media_root=str(tmp_path / "media"),
        external_result_root=str(tmp_path / "processing-import"),
        webodm_enabled=False,
        webodm_url="",
    )

    claimed = await manager.claim_external_job(job_id)
    assert claimed.status == "RUNNING_EXTERNAL"

    with pytest.raises(RuntimeError, match="not claimable from RUNNING_EXTERNAL"):
        await manager.claim_external_job(job_id)


@pytest.mark.asyncio(loop_scope="session")
async def test_failed_thermal_job_requires_explicit_claim_retry(
    tmp_path: Path,
) -> None:
    job_id = __import__("uuid").uuid4()
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        session.add(
            ProcessingJob(
                id=job_id,
                kind="THERMOGRAM",
                status="FAILED_EXTERNAL",
                name="M3T retry claim",
                input_prefix="M3T/retry-claim",
                platform="M3T",
                flight_id=None,
                media_kinds=["WIDE", "THERMAL"],
                options=[],
                image_count=2,
                uploaded_count=0,
                progress=0.0,
                remote_project_id=None,
                remote_task_id=None,
                remote_status=None,
                available_assets=[],
                error="previous failure",
                created_at=now,
                started_at=now,
                updated_at=now,
                finished_at=now,
            )
        )
        await session.commit()

    manager = ProcessingManager(
        session_factory,
        media_root=str(tmp_path / "media"),
        external_result_root=str(tmp_path / "processing-import"),
        webodm_enabled=False,
        webodm_url="",
    )

    with pytest.raises(RuntimeError, match="not claimable from FAILED_EXTERNAL"):
        await manager.claim_external_job(job_id)

    claimed = await manager.claim_external_job(job_id, retry_failed=True)
    assert claimed.status == "RUNNING_EXTERNAL"
    assert claimed.error is None

