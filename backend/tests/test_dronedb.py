from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.models import ProcessingJob, ProcessingJobAsset
from app.processing.dronedb import DroneDBClient
from app.processing.service import M3M_DRONEDB_KINDS, build_dronedb_handoff


def test_dronedb_client_creates_private_dataset_and_uploads_file(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)

        if request.url.path == "/users/authenticate":
            assert request.method == "POST"
            return httpx.Response(200, json={"token": "test-token"})

        assert request.headers.get("Authorization") == "Bearer test-token"

        if request.url.path == "/orgs/m3cloud" and request.method == "GET":
            return httpx.Response(404, json={"message": "not found"})
        if request.url.path == "/orgs" and request.method == "POST":
            body = request.content.decode()
            assert "slug=m3cloud" in body
            assert "isPublic=false" in body
            return httpx.Response(201, json={"slug": "m3cloud"})

        if (
            request.url.path == "/orgs/m3cloud/ds/m3m-test/ex"
            and request.method == "GET"
        ):
            return httpx.Response(404, json={"message": "not found"})
        if (
            request.url.path == "/orgs/m3cloud/ds"
            and request.method == "POST"
        ):
            body = request.content.decode()
            assert "slug=m3m-test" in body
            assert "visibility=Private" in body
            return httpx.Response(201, json={"slug": "m3m-test"})

        if (
            request.url.path == "/orgs/m3cloud/ds/m3m-test/obj"
            and request.method == "POST"
        ):
            body = request.content
            assert b'name="path"' in body
            assert b"raw%2FDJI_0001_D.JPG" not in body
            assert b"raw/DJI_0001_D.JPG" in body
            assert b"m3m-original" in body
            return httpx.Response(
                201,
                json={"path": "raw/DJI_0001_D.JPG", "size": 12},
            )

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    source = tmp_path / "DJI_0001_D.JPG"
    source.write_bytes(b"m3m-original")

    client = DroneDBClient(
        "http://dronedb:5000",
        username="admin",
        password="secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        org = client.ensure_organization("m3cloud", name="M3-Cloud")
        dataset = client.ensure_dataset(
            "m3cloud",
            "m3m-test",
            name="M3M survey",
            tagline="M3-Cloud M3M handoff",
        )
        uploaded = client.upload_file(
            "m3cloud",
            "m3m-test",
            source=source,
            remote_path="raw/DJI_0001_D.JPG",
        )
    finally:
        client.close()

    assert org["slug"] == "m3cloud"
    assert dataset["slug"] == "m3m-test"
    assert uploaded["path"] == "raw/DJI_0001_D.JPG"
    assert requests[0].url.path == "/users/authenticate"


def test_dronedb_upload_retry_accepts_matching_existing_object(
    tmp_path: Path,
) -> None:
    upload_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal upload_attempts

        if request.url.path == "/users/authenticate":
            return httpx.Response(200, json={"token": "test-token"})

        if (
            request.url.path == "/orgs/m3cloud/ds/m3m-test/obj"
            and request.method == "POST"
        ):
            upload_attempts += 1
            return httpx.Response(409, json={"message": "already exists"})

        if (
            request.url.path == "/orgs/m3cloud/ds/m3m-test/obj/list"
            and request.method == "GET"
        ):
            assert request.url.params["path"] == "raw/DJI_0001_MS_NIR.TIF"
            return httpx.Response(
                200,
                json=[
                    {
                        "path": "raw/DJI_0001_MS_NIR.TIF",
                        "size": 7,
                        "hash": "8bb0cf6eb9b17d0f7d22b456f121257dc1254e1f01665370476383ea776df414",
                    }
                ],
            )

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    source = tmp_path / "DJI_0001_MS_NIR.TIF"
    source.write_bytes(b"1234567")

    client = DroneDBClient(
        "http://dronedb:5000",
        username="admin",
        password="secret",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.upload_file(
            "m3cloud",
            "m3m-test",
            source=source,
            remote_path="raw/DJI_0001_MS_NIR.TIF",
        )
    finally:
        client.close()

    assert upload_attempts == 1
    assert result["path"] == "raw/DJI_0001_MS_NIR.TIF"



def test_m3m_handoff_uses_frozen_metadata_and_dataset_relative_paths() -> None:
    now = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
    job_id = uuid.uuid4()
    job = ProcessingJob(
        id=job_id,
        kind="DRONEDB",
        status="QUEUED",
        name="M3M field",
        input_prefix="M3M/field",
        platform="M3M",
        flight_id=None,
        survey_id=None,
        media_kinds=list(M3M_DRONEDB_KINDS),
        options=[
            {"name": "dronedb_org", "value": "m3cloud"},
            {"name": "dronedb_dataset", "value": "m3m-test"},
            {
                "name": "dronedb_dataset_url",
                "value": "http://localhost:5000/orgs/m3cloud/ds/m3m-test",
            },
        ],
        image_count=10,
        uploaded_count=0,
        progress=0.0,
        available_assets=[],
        created_at=now,
        updated_at=now,
    )

    suffixes = {
        "RGB": "_D.JPG",
        "MS_GREEN": "_MS_G.TIF",
        "MS_RED": "_MS_R.TIF",
        "MS_RED_EDGE": "_MS_RE.TIF",
        "MS_NIR": "_MS_NIR.TIF",
    }
    frozen: list[ProcessingJobAsset] = []
    ordinal = 0
    for capture in (1, 2):
        group = f"M3M/field/DJI_{capture:04d}"
        for kind in M3M_DRONEDB_KINDS:
            frozen.append(
                ProcessingJobAsset(
                    job_id=job_id,
                    media_asset_id=uuid.uuid4(),
                    ordinal=ordinal,
                    relative_path=f"{group}{suffixes[kind]}",
                    size_bytes=100 + ordinal,
                    sha256=f"{ordinal:064x}",
                    media_kind=kind,
                    capture_group=group,
                    capture_time_utc=now,
                    metadata_snapshot={
                        "camera": {"model": "M3M"},
                        "snapshot_ordinal": ordinal,
                    },
                )
            )
            ordinal += 1

    handoff = build_dronedb_handoff(job, frozen)

    assert handoff["schema_version"] == 1
    assert handoff["kind"] == "M3CLOUD_M3M_DRONEDB_HANDOFF"
    assert handoff["workflow"] == "DRONEDB"
    assert handoff["platform"] == "M3M"
    assert handoff["source_policy"] == "IMMUTABLE_FROZEN_ORIGINALS"
    assert handoff["capture_group_count"] == 2
    assert handoff["asset_count"] == 10
    assert handoff["required_media_kinds"] == list(M3M_DRONEDB_KINDS)
    assert handoff["remote"] == {
        "organization": "m3cloud",
        "dataset": "m3m-test",
        "url": "http://localhost:5000/orgs/m3cloud/ds/m3m-test",
    }

    assets = handoff["assets"]
    assert isinstance(assets, list)
    assert assets[0]["remote_path"] == "raw/DJI_0001_D.JPG"
    assert assets[-1]["remote_path"] == "raw/DJI_0002_MS_NIR.TIF"
    assert assets[0]["metadata"]["camera"]["model"] == "M3M"
