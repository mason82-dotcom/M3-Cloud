from pathlib import Path
import uuid

import httpx
import pytest

from app.processing.service import (
    REMOTE_STATUS,
    normalize_prefix,
    resolve_asset_path,
    result_object_key,
    selected_result_assets,
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
            "textured_model.glb",
            "../escape.tif",
        ]
    )

    assert selected == [
        "dsm.tif",
        "dtm.tif",
        "orthophoto.tif",
        "textured_model.glb",
    ]
    job_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    assert result_object_key(job_id, "orthophoto.tif") == (
        "webodm/11111111-1111-1111-1111-111111111111/orthophoto.tif"
    )
