from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

import httpx


class DroneDBClient:
    """Minimal DroneDB Registry client for immutable M3M dataset handoff."""

    def __init__(
        self,
        base_url: str,
        *,
        username: str,
        password: str,
        timeout_seconds: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            timeout=timeout_seconds,
            transport=transport,
        )
        self.authenticate(username, password)

    def close(self) -> None:
        self.client.close()

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def authenticate(self, username: str, password: str) -> str:
        response = self.client.post(
            self._url("users/authenticate"),
            data={"username": username, "password": password},
        )
        response.raise_for_status()
        data = response.json()
        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise RuntimeError("DroneDB authentication response did not contain a token")
        self.client.headers["Authorization"] = f"Bearer {token}"
        return token

    def ensure_organization(self, slug: str, *, name: str) -> dict[str, Any]:
        response = self.client.get(self._url(f"orgs/{slug}"))
        if response.status_code == 404:
            response = self.client.post(
                self._url("orgs"),
                data={
                    "slug": slug,
                    "name": name,
                    "description": "Datasets published by M3-Cloud",
                    "isPublic": "false",
                },
            )
        response.raise_for_status()
        data = response.json()
        return dict(data) if isinstance(data, dict) else {}

    def ensure_dataset(
        self,
        org_slug: str,
        dataset_slug: str,
        *,
        name: str,
        tagline: str,
    ) -> dict[str, Any]:
        response = self.client.get(
            self._url(f"orgs/{org_slug}/ds/{dataset_slug}/ex")
        )
        if response.status_code == 404:
            response = self.client.post(
                self._url(f"orgs/{org_slug}/ds"),
                data={
                    "slug": dataset_slug,
                    "name": name,
                    "tagline": tagline,
                },
            )
        response.raise_for_status()
        data = response.json()
        return dict(data) if isinstance(data, dict) else {}

    def upload_file(
        self,
        org_slug: str,
        dataset_slug: str,
        *,
        source: Path,
        remote_path: str,
    ) -> dict[str, Any]:
        mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        with source.open("rb") as handle:
            response = self.client.post(
                self._url(f"orgs/{org_slug}/ds/{dataset_slug}/obj"),
                data={"path": remote_path},
                files={"file": (source.name, handle, mime)},
            )
        response.raise_for_status()
        data = response.json()
        return dict(data) if isinstance(data, dict) else {}

    def upload_bytes(
        self,
        org_slug: str,
        dataset_slug: str,
        *,
        data: bytes,
        remote_path: str,
        filename: str,
        content_type: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            self._url(f"orgs/{org_slug}/ds/{dataset_slug}/obj"),
            data={"path": remote_path},
            files={"file": (filename, data, content_type)},
        )
        response.raise_for_status()
        payload = response.json()
        return dict(payload) if isinstance(payload, dict) else {}
