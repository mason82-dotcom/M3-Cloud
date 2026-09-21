from __future__ import annotations

import io
import urllib.error

import pytest

from thermal_worker.api_client import M3CloudApi, M3CloudApiError


class Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def test_api_retries_transient_transport_failure(monkeypatch):
    calls = []
    sleeps = []

    def urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) == 1:
            raise urllib.error.URLError("temporary")
        return Response(b"[]")

    monkeypatch.setattr("thermal_worker.api_client.urllib.request.urlopen", urlopen)
    monkeypatch.setattr("thermal_worker.api_client.time.sleep", sleeps.append)

    api = M3CloudApi("http://m3-cloud:8000", timeout_seconds=5)
    assert api.list_jobs() == []
    assert len(calls) == 2
    assert sleeps == [1.0]


def test_api_does_not_retry_claim_conflict(monkeypatch):
    calls = []

    def urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        raise urllib.error.HTTPError(
            request.full_url,
            422,
            "Unprocessable Entity",
            hdrs=None,
            fp=io.BytesIO(b'{"detail":"already claimed"}'),
        )

    monkeypatch.setattr("thermal_worker.api_client.urllib.request.urlopen", urlopen)

    api = M3CloudApi("http://m3-cloud:8000")
    with pytest.raises(M3CloudApiError) as captured:
        api.transition("job-1", "RUNNING_EXTERNAL")

    assert captured.value.status == 422
    assert captured.value.detail == "already claimed"
    assert len(calls) == 1

def test_claim_uses_dedicated_endpoint_and_retry_flag(monkeypatch):
    calls = []

    def urlopen(request, timeout):
        calls.append((request.full_url, request.data, timeout))
        return Response(
            b'{"id":"job-1","kind":"THERMOGRAM","platform":"M3T","status":"RUNNING_EXTERNAL"}'
        )

    monkeypatch.setattr("thermal_worker.api_client.urllib.request.urlopen", urlopen)

    api = M3CloudApi("http://m3-cloud:8000", timeout_seconds=7)
    claimed = api.claim("job-1", retry_failed=True)

    assert claimed["status"] == "RUNNING_EXTERNAL"
    assert calls[0][0].endswith(
        "/api/v1/processing/jobs/job-1/external-claim"
    )
    assert __import__("json").loads(calls[0][1]) == {"retry_failed": True}
    assert calls[0][2] == 7

