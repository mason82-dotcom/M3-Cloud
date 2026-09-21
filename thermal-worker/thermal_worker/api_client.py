from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


class M3CloudApiError(RuntimeError):
    def __init__(self, method: str, url: str, status: int, detail: str):
        super().__init__(f"{method} {url} failed with HTTP {status}: {detail}")
        self.method = method
        self.url = url
        self.status = status
        self.detail = detail


class M3CloudApi:
    def __init__(self, base_url: str, *, timeout_seconds: float = 30.0):
        value = base_url.strip().rstrip("/")
        if not value:
            raise ValueError("M3-Cloud API base URL cannot be empty")
        self.base_url = value
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url = self.base_url + path
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "m3cloud-thermal-worker/0.1",
            },
            method=method,
        )
        raw: bytes | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout_seconds,
                ) as response:
                    raw = response.read()
                break
            except urllib.error.HTTPError as exc:
                response_body = exc.read()
                try:
                    decoded = json.loads(response_body) if response_body else {}
                    detail = decoded.get("detail") if isinstance(decoded, dict) else None
                except (UnicodeDecodeError, json.JSONDecodeError):
                    detail = None
                if exc.code in {502, 503, 504} and attempt < 2:
                    time.sleep(float(attempt + 1))
                    continue
                raise M3CloudApiError(
                    method,
                    url,
                    exc.code,
                    str(detail or exc.reason),
                ) from exc
            except urllib.error.URLError as exc:
                if attempt < 2:
                    time.sleep(float(attempt + 1))
                    continue
                raise M3CloudApiError(method, url, 0, str(exc.reason)) from exc

        if raw is None:
            raise M3CloudApiError(method, url, 0, "request produced no response")

        if not raw:
            return None
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise M3CloudApiError(
                method,
                url,
                200,
                "response is not valid JSON",
            ) from exc

    def list_jobs(self) -> list[dict[str, Any]]:
        value = self._request("GET", "/api/v1/processing/jobs")
        if not isinstance(value, list):
            raise TypeError("M3-Cloud processing jobs response must be a list")
        return [item for item in value if isinstance(item, dict)]

    def claim(self, job_id: str, *, retry_failed: bool = False) -> dict[str, Any]:
        value = self._request(
            "POST",
            f"/api/v1/processing/jobs/{job_id}/external-claim",
            {"retry_failed": bool(retry_failed)},
        )
        if not isinstance(value, dict):
            raise TypeError("M3-Cloud claim response must be an object")
        return value

    def thermogram_handoff(self, job_id: str) -> dict[str, Any]:
        value = self._request(
            "GET",
            f"/api/v1/processing/jobs/{job_id}/handoff",
        )
        if not isinstance(value, dict):
            raise TypeError("M3-Cloud thermogram handoff response must be an object")
        return value

    def transition(
        self,
        job_id: str,
        status: str,
        *,
        error: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": status}
        if error:
            payload["error"] = error[:2000]
        value = self._request(
            "POST",
            f"/api/v1/processing/jobs/{job_id}/external-status",
            payload,
        )
        if not isinstance(value, dict):
            raise TypeError("M3-Cloud status response must be an object")
        return value

    def import_results(self, job_id: str) -> list[dict[str, Any]]:
        value = self._request(
            "POST",
            f"/api/v1/processing/jobs/{job_id}/external-results/import",
            {},
        )
        if not isinstance(value, list):
            raise TypeError("M3-Cloud result import response must be a list")
        return [item for item in value if isinstance(item, dict)]
