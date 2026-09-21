from __future__ import annotations

import json
import logging
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .api_client import M3CloudApi, M3CloudApiError
from .processor import ThermalDecoder, process_handoff


logger = logging.getLogger(__name__)


def claim_next_thermogram(
    api: M3CloudApi,
    *,
    retry_failed: bool = False,
) -> dict[str, Any] | None:
    claimable = {"WAITING_EXTERNAL"}
    if retry_failed:
        claimable.add("FAILED_EXTERNAL")

    # The backend returns newest first. Reverse it for FIFO processing.
    for job in reversed(api.list_jobs()):
        if job.get("kind") != "THERMOGRAM" or job.get("platform") != "M3T":
            continue
        if job.get("status") not in claimable:
            continue
        job_id = job.get("id")
        if not isinstance(job_id, str) or not job_id:
            continue
        try:
            claimed = api.transition(job_id, "RUNNING_EXTERNAL")
        except M3CloudApiError as exc:
            # A second worker may have claimed the job between list and transition.
            if exc.status in {409, 422}:
                continue
            raise
        return claimed
    return None


def import_next_completed_thermogram(
    api: M3CloudApi,
) -> dict[str, Any] | None:
    # Recover the narrow crash window after result publication/COMPLETED_EXTERNAL
    # and retry imports that the backend previously marked RESULT_IMPORT_FAILED.
    for job in reversed(api.list_jobs()):
        if job.get("kind") != "THERMOGRAM" or job.get("platform") != "M3T":
            continue
        if job.get("status") not in {"COMPLETED_EXTERNAL", "RESULT_IMPORT_FAILED"}:
            continue
        job_id = job.get("id")
        if not isinstance(job_id, str) or not job_id:
            continue
        imported = api.import_results(job_id)
        return {
            "job_id": job_id,
            "imported_result_count": len(imported),
        }
    return None


def process_claimed_thermogram(
    api: M3CloudApi,
    job: Mapping[str, Any],
    decoder: ThermalDecoder,
    *,
    measurement_overrides: Mapping[str, float] | None = None,
    import_results: bool = True,
) -> dict[str, Any]:
    job_id = job.get("id")
    if not isinstance(job_id, str) or not job_id:
        raise TypeError("Claimed processing job has no string id")

    completed_external = False
    try:
        handoff = api.thermogram_handoff(job_id)
        result_drop_path = handoff.get("result_drop_path")
        if not isinstance(result_drop_path, str) or not result_drop_path:
            raise ValueError("Thermogram handoff is missing result_drop_path")

        with tempfile.TemporaryDirectory(prefix="m3-thermal-handoff-") as temporary:
            handoff_path = Path(temporary) / "handoff.json"
            handoff_path.write_text(
                json.dumps(handoff, ensure_ascii=False),
                encoding="utf-8",
            )
            manifest = process_handoff(
                handoff_path,
                result_drop_path,
                decoder,
                measurement_overrides=measurement_overrides,
            )

        api.transition(job_id, "COMPLETED_EXTERNAL")
        completed_external = True
        imported = api.import_results(job_id) if import_results else []
        return {
            "job_id": job_id,
            "manifest": manifest,
            "imported_result_count": len(imported),
        }
    except Exception as exc:
        if not completed_external:
            try:
                api.transition(
                    job_id,
                    "FAILED_EXTERNAL",
                    error=f"{type(exc).__name__}: {exc}",
                )
            except (M3CloudApiError, TypeError, ValueError):
                logger.exception(
                    "Failed to mark thermal job %s as FAILED_EXTERNAL",
                    job_id,
                )
        raise


def watch_thermograms(
    api: M3CloudApi,
    decoder: ThermalDecoder,
    *,
    poll_seconds: float = 10.0,
    retry_failed: bool = False,
    measurement_overrides: Mapping[str, float] | None = None,
) -> None:
    interval = max(2.0, float(poll_seconds))
    while True:
        try:
            recovered = import_next_completed_thermogram(api)
            if recovered is not None:
                logger.info(
                    "Recovered thermal result import for job %s (%s results)",
                    recovered["job_id"],
                    recovered["imported_result_count"],
                )
                continue
            job = claim_next_thermogram(api, retry_failed=retry_failed)
        except M3CloudApiError:
            logger.exception("M3-Cloud API unavailable while polling thermal jobs")
            time.sleep(interval)
            continue
        if job is None:
            time.sleep(interval)
            continue

        job_id = job.get("id")
        try:
            result = process_claimed_thermogram(
                api,
                job,
                decoder,
                measurement_overrides=measurement_overrides,
                import_results=True,
            )
            logger.info(
                "Thermal job %s completed with %s imported results",
                job_id,
                result["imported_result_count"],
            )
        except Exception:
            logger.exception("Thermal job %s failed", job_id)
