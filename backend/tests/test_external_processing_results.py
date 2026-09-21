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

    def get_object(self, Bucket, Key):
        stored = self.objects[(Bucket, Key)]

        class Body:
            def __init__(self, payload):
                self.payload = payload
                self.closed = False

            def iter_chunks(self, chunk_size):
                for offset in range(0, len(self.payload), chunk_size):
                    yield self.payload[offset:offset + chunk_size]

            def close(self):
                self.closed = True

        return {
            "Body": Body(stored["data"]),
            "ContentType": stored.get("content_type"),
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
        "georeferenced_capture_count": 1,
        "capture_points_geojson": "capture-points.geojson",
        "registration_audit_json": "registration-audit.json",
        "summary_json": "thermal-summary.json",
        "summary_csv": "thermal-summary.csv",
        "summary": {
            "capture_count": 1,
            "georeferenced_capture_count": 1,
            "max_c": 42.5,
            "hotspot_component_count": 1,
            "diagnostic_scope": "HOTSPOT_CANDIDATES_ONLY",
            "registration_status": "NOT_REGISTERED",
            "pair_capture_time_evidence_count": 1,
            "pair_gps_evidence_count": 1,
        },
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
                "registration": {
                    "status": "NOT_REGISTERED",
                    "wide_thermal_coregistered": False,
                    "georeferenced_temperature_raster": False,
                    "pair_audit": {
                        "capture_time_delta_ms": 25.0,
                        "gps_separation_m": 0.03,
                    },
                },
            }
        ],
    }
    (root / "result-manifest.json").write_text(
        __import__("json").dumps(manifest),
        encoding="utf-8",
    )

    details = thermal_result_manifest_details(root, expected_job_id="job")

    capture_points = details["capture-points.geojson"]
    registration_audit = details["registration-audit.json"]
    summary_json = details["thermal-summary.json"]
    summary_csv = details["thermal-summary.csv"]
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

    assert capture_points["result_kind"] == "THERMAL_CAPTURE_POINTS"
    assert capture_points["geometry_scope"] == "CAPTURE_CENTER_ONLY"
    assert capture_points["temperature_pixels_georeferenced"] is False
    assert capture_points["feature_count"] == 1
    assert registration_audit["result_kind"] == "THERMAL_REGISTRATION_AUDIT"
    assert registration_audit["registration_summary"] == {
        "registration_status": "NOT_REGISTERED",
        "capture_count": 1,
        "pair_capture_time_evidence_count": 1,
        "pair_gps_evidence_count": 1,
    }
    assert summary_json["result_kind"] == "THERMAL_SUMMARY"
    assert summary_csv["result_kind"] == "THERMAL_SUMMARY_CSV"
    assert summary_json["thermal_summary"]["max_c"] == 42.5
    assert summary_json["thermal_summary"]["diagnostic_scope"] == "HOTSPOT_CANDIDATES_ONLY"
    assert temperature["result_kind"] == "TEMPERATURE_RASTER"
    assert temperature["temperature_unit"] == "degree_Celsius"
    assert temperature["georeferenced"] is False
    assert temperature["statistics"]["max_c"] == 42.5
    assert temperature["sdk_label"] == "1.8_20251211"
    assert temperature["api_version"] == {"api": 8, "magic": "DIRP"}
    assert temperature["measurement_ranges"]["distance_m"]["max"] == 500.0
    assert temperature["registration"]["status"] == "NOT_REGISTERED"
    assert temperature["registration"]["wide_thermal_coregistered"] is False
    assert temperature["registration"]["pair_audit"]["capture_time_delta_ms"] == 25.0
    assert temperature["registration"]["pair_audit"]["gps_separation_m"] == 0.03
    assert metadata["registration"]["status"] == "NOT_REGISTERED"
    assert hotspots["registration"]["status"] == "NOT_REGISTERED"
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

@pytest.mark.asyncio(loop_scope="session")
async def test_inline_thermal_result_serves_only_classified_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.api_processing import view_processing_result

    job_id = __import__("uuid").uuid4()
    result_id = __import__("uuid").uuid4()
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        session.add(
            ProcessingJob(
                id=job_id,
                kind="THERMOGRAM",
                status="COMPLETED",
                name="M3T inline",
                input_prefix="M3T/inline",
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
                available_assets=["preview.png"],
                error=None,
                created_at=now,
                started_at=now,
                updated_at=now,
                finished_at=now,
            )
        )
        session.add(
            ProcessingResult(
                id=result_id,
                job_id=job_id,
                asset_name="captures/preview.png",
                bucket="m3-results",
                object_key=f"external/{job_id}/captures/preview.png",
                size_bytes=7,
                sha256="a" * 64,
                content_type="image/png",
                details={
                    "thermal_contract": "M3T_THERMAL_RESULTS_V1",
                    "result_kind": "THERMAL_PREVIEW",
                },
                created_at=now,
            )
        )
        await session.commit()

    storage = FakeStorage()
    storage.objects[
        ("m3-results", f"external/{job_id}/captures/preview.png")
    ] = {
        "data": b"pngdata",
        "content_type": "image/png",
    }
    monkeypatch.setattr(
        "app.api_processing.create_storage_client",
        lambda: storage,
    )

    response = await view_processing_result(job_id, result_id)
    payload = b"".join([chunk async for chunk in response.body_iterator])

    assert response.media_type == "image/png"
    assert response.headers["content-disposition"] == "inline"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert payload == b"pngdata"

