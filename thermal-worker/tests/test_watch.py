from __future__ import annotations

from pathlib import Path

import pytest

from thermal_worker.api_client import M3CloudApiError
from thermal_worker.watch import claim_next_thermogram, process_claimed_thermogram


class FakeApi:
    def __init__(self, jobs):
        self.jobs = jobs
        self.transitions = []
        self.imported = []
        self.handoffs = {}

    def list_jobs(self):
        return list(self.jobs)

    def transition(self, job_id, status, *, error=None):
        self.transitions.append((job_id, status, error))
        return {
            "id": job_id,
            "kind": "THERMOGRAM",
            "platform": "M3T",
            "status": status,
        }

    def thermogram_handoff(self, job_id):
        return self.handoffs[job_id]

    def import_results(self, job_id):
        self.imported.append(job_id)
        return [{"id": "result-1"}]


def test_claim_next_thermogram_uses_fifo_and_ignores_other_jobs():
    api = FakeApi(
        [
            {
                "id": "new",
                "kind": "THERMOGRAM",
                "platform": "M3T",
                "status": "WAITING_EXTERNAL",
            },
            {
                "id": "webodm",
                "kind": "WEBODM",
                "platform": "M3E",
                "status": "WAITING_EXTERNAL",
            },
            {
                "id": "old",
                "kind": "THERMOGRAM",
                "platform": "M3T",
                "status": "WAITING_EXTERNAL",
            },
        ]
    )

    claimed = claim_next_thermogram(api)

    assert claimed["id"] == "old"
    assert api.transitions == [("old", "RUNNING_EXTERNAL", None)]


def test_claim_skips_job_lost_to_another_worker():
    class RacingApi(FakeApi):
        def transition(self, job_id, status, *, error=None):
            if job_id == "old":
                raise M3CloudApiError("POST", "http://m3/jobs/old", 422, "already claimed")
            return super().transition(job_id, status, error=error)

    api = RacingApi(
        [
            {
                "id": "new",
                "kind": "THERMOGRAM",
                "platform": "M3T",
                "status": "WAITING_EXTERNAL",
            },
            {
                "id": "old",
                "kind": "THERMOGRAM",
                "platform": "M3T",
                "status": "WAITING_EXTERNAL",
            },
        ]
    )

    claimed = claim_next_thermogram(api)

    assert claimed["id"] == "new"
    assert api.transitions == [("new", "RUNNING_EXTERNAL", None)]


def test_failed_job_requires_explicit_retry_flag():
    jobs = [
        {
            "id": "failed",
            "kind": "THERMOGRAM",
            "platform": "M3T",
            "status": "FAILED_EXTERNAL",
        }
    ]
    api = FakeApi(jobs)

    assert claim_next_thermogram(api) is None
    claimed = claim_next_thermogram(api, retry_failed=True)

    assert claimed["id"] == "failed"


def test_process_claimed_job_completes_and_imports(tmp_path, monkeypatch):
    api = FakeApi([])
    job = {
        "id": "job-1",
        "kind": "THERMOGRAM",
        "platform": "M3T",
        "status": "RUNNING_EXTERNAL",
    }
    result_path = tmp_path / "results" / "job-1"
    api.handoffs["job-1"] = {
        "schema_version": 3,
        "worker_contract": "M3T_RJPEG_V1",
        "workflow": "THERMOGRAM",
        "platform": "M3T",
        "job_id": "job-1",
        "external_path": str(tmp_path / "media"),
        "result_drop_path": str(result_path),
        "capture_groups": [],
    }
    called = {}

    def fake_process(handoff_path, output_root, decoder, *, measurement_overrides=None):
        called["handoff_path"] = Path(handoff_path)
        called["output_root"] = output_root
        called["decoder"] = decoder
        called["measurement_overrides"] = measurement_overrides
        assert called["handoff_path"].is_file()
        return {"contract": "M3T_THERMAL_RESULTS_V1"}

    monkeypatch.setattr("thermal_worker.watch.process_handoff", fake_process)
    decoder = object()

    result = process_claimed_thermogram(
        api,
        job,
        decoder,
        measurement_overrides={"emissivity": 0.95},
    )

    assert called["output_root"] == str(result_path)
    assert called["decoder"] is decoder
    assert called["measurement_overrides"] == {"emissivity": 0.95}
    assert api.transitions == [("job-1", "COMPLETED_EXTERNAL", None)]
    assert api.imported == ["job-1"]
    assert result["imported_result_count"] == 1


def test_process_failure_marks_job_failed(tmp_path, monkeypatch):
    api = FakeApi([])
    job = {
        "id": "job-2",
        "kind": "THERMOGRAM",
        "platform": "M3T",
        "status": "RUNNING_EXTERNAL",
    }
    api.handoffs["job-2"] = {
        "result_drop_path": str(tmp_path / "results" / "job-2"),
    }

    def fail(*_args, **_kwargs):
        raise RuntimeError("decode failed")

    monkeypatch.setattr("thermal_worker.watch.process_handoff", fail)

    with pytest.raises(RuntimeError, match="decode failed"):
        process_claimed_thermogram(api, job, object())

    assert api.transitions == [
        ("job-2", "FAILED_EXTERNAL", "RuntimeError: decode failed")
    ]
    assert api.imported == []
