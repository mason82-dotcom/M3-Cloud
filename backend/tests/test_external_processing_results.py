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
        "capture_groups": [
            {
                "capture_group": "M3T/site/DJI_0001",
                "temperature_tif": (
                    "captures/00001_DJI_0001_deadbeef00/temperature.tif"
                ),
                "preview_png": "captures/00001_DJI_0001_deadbeef00/preview.png",
                "thermal_json": "captures/00001_DJI_0001_deadbeef00/thermal.json",
                "statistics": {"min_c": 20.0, "max_c": 42.5},
                "width": 640,
                "height": 512,
                "sdk_label": "1.8_20251211",
                "measurement_mode": "sdk_native",
            }
        ],
    }
    (root / "result-manifest.json").write_text(
        __import__("json").dumps(manifest),
        encoding="utf-8",
    )

    details = thermal_result_manifest_details(root)

    temperature = details[
        "captures/00001_DJI_0001_deadbeef00/temperature.tif"
    ]
    preview = details["captures/00001_DJI_0001_deadbeef00/preview.png"]
    metadata = details["captures/00001_DJI_0001_deadbeef00/thermal.json"]

    assert temperature["result_kind"] == "TEMPERATURE_RASTER"
    assert temperature["temperature_unit"] == "degree_Celsius"
    assert temperature["georeferenced"] is False
    assert temperature["statistics"]["max_c"] == 42.5
    assert temperature["sdk_label"] == "1.8_20251211"
    assert preview["result_kind"] == "THERMAL_PREVIEW"
    assert metadata["result_kind"] == "THERMAL_METADATA"
    assert details["result-manifest.json"]["result_kind"] == "THERMAL_MANIFEST"
