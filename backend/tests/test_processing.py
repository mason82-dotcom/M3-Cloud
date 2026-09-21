from pathlib import Path
import uuid

import httpx
import pytest

from app.processing.service import (
    REMOTE_STATUS,
    normalize_prefix,
    resolve_asset_path,
    build_thermogram_handoff,
    external_result_object_key,
    result_object_key,
    select_thermogram_assets,
    selected_result_assets,
    verify_frozen_input,
)
from app.processing.webodm import WebODMClient


def test_processing_prefix_stays_inside_media_root(tmp_path: Path) -> None:
    assert normalize_prefix("M3E/site-a") == "M3E/site-a"

    with pytest.raises(ValueError):
        normalize_prefix("../outside")

    safe = resolve_asset_path(tmp_path, "M3E/site-a/image.JPG")
    assert safe == tmp_path.resolve() / "M3E/site-a/image.JPG"

    with pytest.raises(ValueError):
        resolve_asset_path(tmp_path, "../secret.JPG")


def test_webodm_partial_upload_flow(tmp_path: Path) -> None:
    image = tmp_path / "DJI_0001.JPG"
    image.write_bytes(b"original-image-bytes")

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/projects/":
            return httpx.Response(201, json={"id": 7})
        if request.url.path == "/api/projects/7/tasks/":
            return httpx.Response(201, json={"id": 9})
        if request.url.path == "/api/projects/7/tasks/9/upload/":
            body = request.read()
            assert b"original-image-bytes" in body
            return httpx.Response(201, json={})
        if request.url.path == "/api/projects/7/tasks/9/commit/":
            return httpx.Response(200, json={"id": 9, "status": 10})
        if request.url.path == "/api/projects/7/tasks/9/download/orthophoto.tif":
            return httpx.Response(
                200,
                content=b"geotiff-result",
                headers={"Content-Type": "image/tiff"},
            )
        if request.url.path == "/api/projects/7/tasks/9/":
            return httpx.Response(
                200,
                json={
                    "id": 9,
                    "status": 20,
                    "running_progress": 0.25,
                    "available_assets": [],
                },
            )
        return httpx.Response(404)

    client = WebODMClient(
        "http://webodm.test",
        token="abc",
        transport=httpx.MockTransport(handler),
    )
    try:
        project_id = client.create_project("site-a")
        task_id = client.create_partial_task(
            project_id,
            name="site-a",
            options=[{"name": "fast-orthophoto", "value": True}],
        )
        client.upload_image(project_id, task_id, image)
        committed = client.commit_task(project_id, task_id)
        task = client.get_task(project_id, task_id)
        destination = tmp_path / "orthophoto.tif"
        size, content_type, sha256 = client.download_asset(
            project_id,
            task_id,
            "orthophoto.tif",
            destination,
        )
    finally:
        client.close()

    assert committed["status"] == 10
    assert size == len(b"geotiff-result")
    assert content_type == "image/tiff"
    assert len(sha256) == 64
    assert destination.read_bytes() == b"geotiff-result"
    assert task["status"] == 20
    assert calls == [
        ("POST", "/api/projects/"),
        ("POST", "/api/projects/7/tasks/"),
        ("POST", "/api/projects/7/tasks/9/upload/"),
        ("POST", "/api/projects/7/tasks/9/commit/"),
        ("GET", "/api/projects/7/tasks/9/"),
        ("GET", "/api/projects/7/tasks/9/download/orthophoto.tif"),
    ]



def test_webodm_remote_queue_state_is_distinct() -> None:
    assert REMOTE_STATUS[10] == "QUEUED_REMOTE"
    assert REMOTE_STATUS[20] == "RUNNING"
    assert REMOTE_STATUS[40] == "IMPORTING_RESULTS"


def test_webodm_result_selection_skips_monolithic_archive() -> None:
    selected = selected_result_assets(
        [
            "all.zip",
            "orthophoto.tif",
            "dsm.tif",
            "dtm.tif",
            "dsm_tiles.zip",
            "dtm_tiles.zip",
            "textured_model.glb",
            "../escape.tif",
        ]
    )

    assert selected == [
        "dsm.tif",
        "dsm_tiles.zip",
        "dtm.tif",
        "dtm_tiles.zip",
        "orthophoto.tif",
        "textured_model.glb",
    ]
    job_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    assert result_object_key(job_id, "orthophoto.tif") == (
        "webodm/11111111-1111-1111-1111-111111111111/orthophoto.tif"
    )



def _m3t_asset(kind: str, group: str, filename: str):
    from datetime import datetime, timezone
    from app.models import MediaAsset

    now = datetime.now(timezone.utc)
    return MediaAsset(
        id=uuid.uuid4(),
        relative_path=f"M3T/site/{filename}",
        filename=filename,
        extension=".jpg",
        size_bytes=100,
        mtime_ns=1,
        sha256=uuid.uuid4().hex * 2,
        platform="M3T",
        media_kind=kind,
        capture_group=group,
        storage_mode="EXTERNAL",
        external_root="media-import",
        present=True,
        duplicate_of=None,
        discovered_at=now,
        last_seen_at=now,
    )


def test_thermogram_selection_freezes_only_complete_m3t_pairs() -> None:
    complete = "M3T/site/DJI_0001"
    incomplete = "M3T/site/DJI_0002"
    assets = [
        _m3t_asset("WIDE", complete, "DJI_0001_W.JPG"),
        _m3t_asset("THERMAL", complete, "DJI_0001_T.JPG"),
        _m3t_asset("WIDE", incomplete, "DJI_0002_W.JPG"),
    ]

    selected = select_thermogram_assets(assets)

    assert [asset.media_kind for asset in selected] == ["WIDE", "THERMAL"]
    assert {asset.capture_group for asset in selected} == {complete}


def test_thermogram_handoff_is_m3t_and_preserves_original_paths() -> None:
    from datetime import datetime, timezone
    from app.models import ProcessingJob

    group = "M3T/site/DJI_0001"
    assets = [
        _m3t_asset("WIDE", group, "DJI_0001_W.JPG"),
        _m3t_asset("THERMAL", group, "DJI_0001_T.JPG"),
    ]
    now = datetime.now(timezone.utc)
    job = ProcessingJob(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        kind="THERMOGRAM",
        status="WAITING_EXTERNAL",
        name="M3T site",
        input_prefix="M3T/site",
        platform="M3T",
        flight_id=None,
        media_kinds=["WIDE", "THERMAL"],
        options=[],
        image_count=2,
        uploaded_count=0,
        progress=0.0,
        available_assets=[],
        created_at=now,
        updated_at=now,
    )

    handoff = build_thermogram_handoff(
        job,
        assets,
        handoff_root=r"\\m3-cloud\media-import",
    )

    assert handoff["schema_version"] == 3
    assert handoff["workflow"] == "THERMOGRAM"
    assert handoff["worker_contract"] == "M3T_RJPEG_V1"
    assert handoff["platform"] == "M3T"
    assert handoff["capture_group_count"] == 1
    assert handoff["asset_count"] == 2
    assert handoff["external_path"] == r"\\m3-cloud\media-import\M3T\site"
    files = handoff["capture_groups"][0]["files"]
    assert [item["filename"] for item in files] == [
        "DJI_0001_W.JPG",
        "DJI_0001_T.JPG",
    ]
    assert [item["path_relative_to_input"] for item in files] == [
        "DJI_0001_W.JPG",
        "DJI_0001_T.JPG",
    ]


def test_external_result_object_key_is_job_scoped() -> None:
    job_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
    assert external_result_object_key(job_id, "reports/result.csv") == (
        "external/33333333-3333-3333-3333-333333333333/reports/result.csv"
    )
    with pytest.raises(ValueError):
        external_result_object_key(job_id, "../escape.csv")


def test_external_result_snapshot_is_stable_and_hashed(tmp_path: Path) -> None:
    from app.processing.service import ProcessingManager

    source = tmp_path / "result.csv"
    destination = tmp_path / "snapshot.csv"
    source.write_bytes(b"temperature,42.1\n")

    size, sha256 = ProcessingManager._snapshot_external_result(
        source,
        destination,
    )

    assert size == len(b"temperature,42.1\n")
    assert len(sha256) == 64
    assert destination.read_bytes() == source.read_bytes()


def test_frozen_processing_input_detects_source_change(tmp_path: Path) -> None:
    path = tmp_path / "DJI_0001.JPG"
    path.write_bytes(b"original")
    expected_size = len(b"original")
    expected_sha = __import__("hashlib").sha256(b"original").hexdigest()

    verify_frozen_input(
        path,
        expected_size=expected_size,
        expected_sha256=expected_sha,
    )

    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed after job creation"):
        verify_frozen_input(
            path,
            expected_size=expected_size,
            expected_sha256=expected_sha,
        )
