from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .dji_sdk import DjiThermalSdk
from .processor import process_handoff


def _post_json(url: str, payload: dict[str, Any] | None = None) -> Any:
    data = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def _job_url(api_base: str, job_id: str, suffix: str) -> str:
    return (
        api_base.rstrip("/")
        + f"/api/v1/processing/jobs/{job_id}/{suffix.lstrip('/')}"
    )


def _status(api_base: str, job_id: str, status: str, error: str | None = None) -> None:
    payload: dict[str, Any] = {"status": status}
    if error:
        payload["error"] = error[:2000]
    _post_json(_job_url(api_base, job_id, "external-status"), payload)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Process an M3-Cloud M3T radiometric handoff with DJI Thermal SDK.",
    )
    parser.add_argument("handoff", help="Path to m3t-thermogram-handoff.json")
    parser.add_argument(
        "--sdk-dir",
        default=os.environ.get("DJI_TSDK_DIR", ""),
        help="DJI Thermal SDK root/release directory (or DJI_TSDK_DIR).",
    )
    parser.add_argument(
        "--sdk-label",
        default=os.environ.get("DJI_TSDK_VERSION"),
        help="Provenance label such as 1.8_20251211.",
    )
    parser.add_argument(
        "--result-dir",
        help="Output directory; defaults to handoff.result_drop_path.",
    )
    parser.add_argument("--distance-m", type=float)
    parser.add_argument("--humidity-pct", type=float)
    parser.add_argument("--emissivity", type=float)
    parser.add_argument("--reflection-c", type=float)
    parser.add_argument("--ambient-temp-c", type=float)
    parser.add_argument(
        "--api-base",
        help="Optional M3-Cloud base URL for external job status callbacks.",
    )
    parser.add_argument(
        "--import-results",
        action="store_true",
        help="After successful processing, ask M3-Cloud to import the result folder.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handoff_path = Path(args.handoff)
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    if not isinstance(handoff, dict):
        raise TypeError("Thermogram handoff must be a JSON object")

    job_id = handoff.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise ValueError("Thermogram handoff is missing job_id")

    result_dir = args.result_dir or handoff.get("result_drop_path")
    if not isinstance(result_dir, str) or not result_dir:
        raise ValueError("No result directory supplied and handoff has no result_drop_path")
    if not args.sdk_dir:
        raise ValueError("DJI Thermal SDK path required via --sdk-dir or DJI_TSDK_DIR")
    if args.import_results and not args.api_base:
        raise ValueError("--import-results requires --api-base")

    overrides = {
        key: value
        for key, value in {
            "distance_m": args.distance_m,
            "humidity_pct": args.humidity_pct,
            "emissivity": args.emissivity,
            "reflection_c": args.reflection_c,
            "ambient_temp_c": args.ambient_temp_c,
        }.items()
        if value is not None
    }

    callback_started = False
    try:
        if args.api_base:
            _status(args.api_base, job_id, "RUNNING_EXTERNAL")
            callback_started = True

        decoder = DjiThermalSdk(args.sdk_dir, sdk_label=args.sdk_label)
        manifest = process_handoff(
            handoff_path,
            result_dir,
            decoder,
            measurement_overrides=overrides,
        )

        if args.api_base:
            _status(args.api_base, job_id, "COMPLETED_EXTERNAL")
            if args.import_results:
                _post_json(_job_url(args.api_base, job_id, "external-results/import"))

        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        if args.api_base and callback_started:
            try:
                _status(
                    args.api_base,
                    job_id,
                    "FAILED_EXTERNAL",
                    f"{type(exc).__name__}: {exc}",
                )
            except (OSError, urllib.error.URLError, ValueError):
                pass
        raise


if __name__ == "__main__":
    sys.exit(main())
