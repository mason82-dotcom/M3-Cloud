from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

import httpx


class WebODMClient:
    """Minimal WebODM client using the partial-task upload flow."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str = "",
        username: str = "",
        password: str = "",
        timeout_seconds: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            timeout=timeout_seconds,
            transport=transport,
        )
        if token:
            self.client.headers["Authorization"] = f"JWT {token}"
        elif username and password:
            self.authenticate(username, password)

    def close(self) -> None:
        self.client.close()

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/{path.lstrip('/')}"

    def authenticate(self, username: str, password: str) -> str:
        response = self.client.post(
            self._url("token-auth/"),
            data={"username": username, "password": password},
        )
        response.raise_for_status()
        token = str(response.json()["token"])
        self.client.headers["Authorization"] = f"JWT {token}"
        return token

    def create_project(self, name: str) -> int:
        response = self.client.post(
            self._url("projects/"),
            data={"name": name},
        )
        response.raise_for_status()
        return int(response.json()["id"])

    def create_partial_task(
        self,
        project_id: int,
        *,
        name: str,
        options: list[dict[str, Any]],
    ) -> int:
        response = self.client.post(
            self._url(f"projects/{project_id}/tasks/"),
            data={
                "name": name,
                "partial": "true",
                "auto_processing_node": "true",
                "options": json.dumps(options),
            },
        )
        response.raise_for_status()
        return int(response.json()["id"])

    def upload_image(self, project_id: int, task_id: int, image: Path) -> None:
        mime = mimetypes.guess_type(image.name)[0] or "application/octet-stream"
        with image.open("rb") as handle:
            response = self.client.post(
                self._url(f"projects/{project_id}/tasks/{task_id}/upload/"),
                files={"images": (image.name, handle, mime)},
            )
        response.raise_for_status()

    def commit_task(self, project_id: int, task_id: int) -> dict[str, Any]:
        response = self.client.post(
            self._url(f"projects/{project_id}/tasks/{task_id}/commit/"),
        )
        response.raise_for_status()
        data = response.json()
        return dict(data) if isinstance(data, dict) else {}

    def get_task(self, project_id: int, task_id: int) -> dict[str, Any]:
        response = self.client.get(
            self._url(f"projects/{project_id}/tasks/{task_id}/"),
        )
        response.raise_for_status()
        data = response.json()
        return dict(data) if isinstance(data, dict) else {}
