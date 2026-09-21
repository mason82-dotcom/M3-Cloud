from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .api_client import M3CloudApi, M3CloudApiError
from .dji_sdk import DjiThermalSdk
from .processor import process_handoff
from .watch import watch_thermograms


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Process M3-Cloud M3T radiometric R-JPEGs with DJI Thermal SDK.",
    )
    parser.add_argument(
        "handoff",
        nargs="?",
        help="Path to m3t-thermogram-handoff.json for one-shot processing.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously claim and process WAITING_EXTERNAL M3T Thermogram jobs.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=10.0,
        help="Watch-mode polling interval (minimum 2 seconds).",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Watch mode may also reclaim FAILED_EXTERNAL jobs.",
    )
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
        help="One-shot output directory; defaults to handoff.result_drop_path.",
    )
    parser.add_argument("--distance-m", type=float)
    parser.add_argument("--humidity-pct", type=float)
    parser.add_argument("--emissivity", type=float)
    parser.add_argument("--reflection-c", type=float)
    parser.add_argument("--ambient-temp-c", type=float)
    parser.add_argument(
        "--hotspot-delta-c",
        type=float,
        default=float(os.environ.get("M3_THERMAL_HOTSPOT_DELTA_C", "10")),
        help="Generic hotspot candidate threshold above image median in °C.",
    )
    parser.add_argument(
        "--hotspot-min-pixels",
        type=int,
        default=int(os.environ.get("M3_THERMAL_HOTSPOT_MIN_PIXELS", "4")),
        help="Minimum 4-connected candidate component size in thermal pixels.",
    )
    parser.add_argument(
        "--api-base",
        default=os.environ.get("M3CLOUD_API_BASE"),
        help="M3-Cloud base URL (or M3CLOUD_API_BASE). Required for --watch.",
    )
    parser.add_argument(
        "--import-results",
        action="store_true",
        help="One-shot mode: import result folder into M3-Cloud after processing.",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("M3_THERMAL_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser


def _overrides(args: argparse.Namespace) -> dict[str, float]:
    return {
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


def _run_one_shot(
    args: argparse.Namespace,
    decoder: DjiThermalSdk,
    overrides: dict[str, float],
) -> int:
    if not args.handoff:
        raise ValueError("Handoff path is required unless --watch is used")

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
    if args.import_results and not args.api_base:
        raise ValueError("--import-results requires --api-base")

    api = M3CloudApi(args.api_base) if args.api_base else None
    callback_started = False
    completed_external = False
    try:
        if api is not None:
            api.transition(job_id, "RUNNING_EXTERNAL")
            callback_started = True

        manifest = process_handoff(
            handoff_path,
            result_dir,
            decoder,
            measurement_overrides=overrides,
            hotspot_delta_c=args.hotspot_delta_c,
            hotspot_min_pixels=args.hotspot_min_pixels,
        )

        if api is not None:
            api.transition(job_id, "COMPLETED_EXTERNAL")
            completed_external = True
            if args.import_results:
                api.import_results(job_id)

        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        if api is not None and callback_started and not completed_external:
            try:
                api.transition(
                    job_id,
                    "FAILED_EXTERNAL",
                    error=f"{type(exc).__name__}: {exc}",
                )
            except (M3CloudApiError, TypeError, ValueError):
                logging.getLogger(__name__).exception(
                    "Failed to mark thermal job %s as FAILED_EXTERNAL",
                    job_id,
                )
        raise


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.sdk_dir:
        raise ValueError("DJI Thermal SDK path required via --sdk-dir or DJI_TSDK_DIR")
    if args.watch and args.handoff:
        raise ValueError("Do not supply a handoff path together with --watch")
    if args.watch and args.result_dir:
        raise ValueError("--result-dir is only valid for one-shot handoff processing")
    if args.watch and not args.api_base:
        raise ValueError("--watch requires --api-base or M3CLOUD_API_BASE")

    overrides = _overrides(args)
    decoder = DjiThermalSdk(args.sdk_dir, sdk_label=args.sdk_label)

    if args.watch:
        api = M3CloudApi(args.api_base)
        watch_thermograms(
            api,
            decoder,
            poll_seconds=args.poll_seconds,
            retry_failed=args.retry_failed,
            measurement_overrides=overrides,
            hotspot_delta_c=args.hotspot_delta_c,
            hotspot_min_pixels=args.hotspot_min_pixels,
        )
        return 0

    return _run_one_shot(args, decoder, overrides)


if __name__ == "__main__":
    sys.exit(main())
