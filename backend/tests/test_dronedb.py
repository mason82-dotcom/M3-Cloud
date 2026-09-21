from __future__ import annotations

from pathlib import Path

import httpx

from app.processing.dronedb import DroneDBClient


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
