from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

import numpy as np
import tifffile
from PIL import Image

from .dji_sdk import DecodeResult


RESULT_CONTRACT = "M3T_THERMAL_RESULTS_V1"


class ThermalDecoder(Protocol):
    def decode_file(
        self,
        path: str | Path,
        *,
        overrides: Mapping[str, float] | None = None,
    ) -> DecodeResult: ...


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            size += len(block)
    return size, digest.hexdigest()


def _safe_relative_path(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe handoff path: {value!r}")
    return path


def _source_path(root: Path, item: Mapping[str, Any]) -> Path:
    relative = item.get("path_relative_to_input")
    if not isinstance(relative, str) or not relative.strip():
        # Schema v2 fallback. It is safe only for flat handoffs, which is how the
        # original contract was used before path_relative_to_input existed.
        relative = item.get("filename")
    if not isinstance(relative, str):
        raise TypeError("Thermogram file is missing string path_relative_to_input/filename")
    safe = _safe_relative_path(relative)
    return root.joinpath(*safe.parts)


def _verify_source(path: Path, item: Mapping[str, Any]) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    expected_size = item.get("size_bytes")
    expected_sha256 = item.get("sha256")
    size, sha256 = _sha256_file(path)
    if isinstance(expected_size, int) and size != expected_size:
        raise ValueError(
            f"Frozen input size mismatch for {path.name}: {size} != {expected_size}"
        )
    if isinstance(expected_sha256, str) and expected_sha256 and sha256 != expected_sha256:
        raise ValueError(f"Frozen input SHA256 mismatch for {path.name}")


def _stats(temperature: np.ndarray) -> dict[str, float | int]:
    finite = temperature[np.isfinite(temperature)]
    if finite.size == 0:
        raise ValueError("Temperature plane contains no finite samples")
    return {
        "min_c": float(np.min(finite)),
        "max_c": float(np.max(finite)),
        "mean_c": float(np.mean(finite)),
        "stddev_c": float(np.std(finite)),
        "p02_c": float(np.percentile(finite, 2)),
        "p50_c": float(np.percentile(finite, 50)),
        "p98_c": float(np.percentile(finite, 98)),
        "finite_pixels": int(finite.size),
        "invalid_pixels": int(temperature.size - finite.size),
    }


def _preview(temperature: np.ndarray, statistics: Mapping[str, float | int]) -> Image.Image:
    low = float(statistics["p02_c"])
    high = float(statistics["p98_c"])
    if not math.isfinite(low) or not math.isfinite(high) or high <= low:
        low = float(statistics["min_c"])
        high = float(statistics["max_c"])
    if high <= low:
        normalized = np.zeros(temperature.shape, dtype=np.uint8)
    else:
        safe = np.nan_to_num(temperature, nan=low, posinf=high, neginf=low)
        normalized = np.clip((safe - low) / (high - low), 0.0, 1.0)
        normalized = np.rint(normalized * 255.0).astype(np.uint8)
    return Image.fromarray(normalized, mode="L")


def _capture_output_name(index: int, capture_group: str) -> str:
    base = PurePosixPath(capture_group).name or f"capture-{index:05d}"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", base).strip("._") or "capture"
    short_hash = hashlib.sha1(capture_group.encode("utf-8")).hexdigest()[:10]
    return f"{index:05d}_{safe}_{short_hash}"


def _write_temperature_tiff(
    path: Path,
    temperature: np.ndarray,
    *,
    source_sha256: str | None,
    sdk_label: str,
) -> None:
    description = {
        "schema_version": 1,
        "quantity": "temperature",
        "unit": "degree_Celsius",
        "source_sha256": source_sha256,
        "decoder": "DJI_DIRP",
        "sdk_label": sdk_label,
        "georeferenced": False,
    }
    tifffile.imwrite(
        path,
        np.asarray(temperature, dtype=np.float32),
        dtype=np.float32,
        photometric="minisblack",
        metadata=description,
    )


def process_handoff(
    handoff_path: str | Path,
    output_root: str | Path,
    decoder: ThermalDecoder,
    *,
    measurement_overrides: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    handoff_file = Path(handoff_path)
    handoff = json.loads(handoff_file.read_text(encoding="utf-8"))
    if not isinstance(handoff, dict):
        raise TypeError("Thermogram handoff must contain a JSON object")
    if handoff.get("workflow") != "THERMOGRAM" or handoff.get("platform") != "M3T":
        raise ValueError("Handoff is not an M3T THERMOGRAM workflow")
    schema_version = handoff.get("schema_version")
    if schema_version not in {2, 3}:
        raise ValueError(f"Unsupported thermogram handoff schema: {schema_version}")
    if schema_version == 3 and handoff.get("worker_contract") != "M3T_RJPEG_V1":
        raise ValueError("Unsupported M3T thermal worker contract")

    external_path = handoff.get("external_path")
    if not isinstance(external_path, str) or not external_path.strip():
        raise ValueError("Thermogram handoff has no external_path")
    source_root = Path(external_path)
    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)

    groups = handoff.get("capture_groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("Thermogram handoff contains no capture groups")

    results: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            raise TypeError("Invalid capture group entry")
        capture_group = group.get("capture_group")
        if not isinstance(capture_group, str) or not capture_group:
            raise TypeError("Capture group is missing its string identifier")
        files = group.get("files")
        if not isinstance(files, list):
            raise TypeError(f"Capture group {capture_group} has no file list")

        by_kind = {
            item.get("media_kind"): item
            for item in files
            if isinstance(item, dict) and isinstance(item.get("media_kind"), str)
        }
        thermal_item = by_kind.get("THERMAL")
        wide_item = by_kind.get("WIDE")
        if not isinstance(thermal_item, dict) or not isinstance(wide_item, dict):
            raise ValueError(
                f"Capture group {capture_group} is missing WIDE/THERMAL pair"
            )

        thermal_path = _source_path(source_root, thermal_item)
        wide_path = _source_path(source_root, wide_item)
        _verify_source(thermal_path, thermal_item)
        _verify_source(wide_path, wide_item)

        decoded = decoder.decode_file(
            thermal_path,
            overrides=measurement_overrides,
        )
        temperature = np.asarray(decoded.temperature_c, dtype=np.float32)
        if temperature.shape != (decoded.height, decoded.width):
            raise ValueError(
                f"Decoder shape mismatch for {thermal_path.name}: "
                f"{temperature.shape} != {(decoded.height, decoded.width)}"
            )

        statistics = _stats(temperature)
        folder = destination / "captures" / _capture_output_name(index, capture_group)
        folder.mkdir(parents=True, exist_ok=True)
        temperature_path = folder / "temperature.tif"
        preview_path = folder / "preview.png"
        metadata_path = folder / "thermal.json"

        _write_temperature_tiff(
            temperature_path,
            temperature,
            source_sha256=(
                str(thermal_item.get("sha256"))
                if thermal_item.get("sha256") is not None
                else None
            ),
            sdk_label=decoded.sdk_label,
        )
        preview = _preview(temperature, statistics)
        preview.save(preview_path, format="PNG")

        thermal_metadata: dict[str, Any] = {
            "schema_version": 1,
            "contract": RESULT_CONTRACT,
            "capture_group": capture_group,
            "source": {
                "thermal": {
                    "relative_path": thermal_item.get("relative_path"),
                    "path_relative_to_input": thermal_item.get("path_relative_to_input"),
                    "filename": thermal_item.get("filename"),
                    "size_bytes": thermal_item.get("size_bytes"),
                    "sha256": thermal_item.get("sha256"),
                    "capture_time_utc": thermal_item.get("capture_time_utc"),
                    "metadata": thermal_item.get("metadata") or {},
                },
                "wide": {
                    "relative_path": wide_item.get("relative_path"),
                    "path_relative_to_input": wide_item.get("path_relative_to_input"),
                    "filename": wide_item.get("filename"),
                    "size_bytes": wide_item.get("size_bytes"),
                    "sha256": wide_item.get("sha256"),
                    "capture_time_utc": wide_item.get("capture_time_utc"),
                    "metadata": wide_item.get("metadata") or {},
                },
            },
            "radiometry": {
                "decoder": "DJI_DIRP",
                "sdk_label": decoded.sdk_label,
                "rjpeg_version": decoded.rjpeg_version,
                "width": decoded.width,
                "height": decoded.height,
                "dtype": "float32",
                "unit": "degree_Celsius",
                "measurement_mode": decoded.measurement_mode,
                "measurement_error_code": decoded.measurement_error_code,
                "measurement_params": (
                    decoded.measurement_params.as_dict()
                    if decoded.measurement_params is not None
                    else None
                ),
                "requested_overrides": dict(measurement_overrides or {}),
                "statistics": statistics,
            },
            "registration": {
                "wide_thermal_coregistered": False,
                "georeferenced_temperature_raster": False,
                "note": (
                    "Temperature TIFF is sensor-pixel space only. "
                    "WIDE/THERMAL registration and map georeferencing are separate stages."
                ),
            },
            "artifacts": {
                "temperature_tif": temperature_path.relative_to(destination).as_posix(),
                "preview_png": preview_path.relative_to(destination).as_posix(),
            },
        }
        metadata_path.write_text(
            json.dumps(thermal_metadata, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

        results.append(
            {
                "capture_group": capture_group,
                "temperature_tif": temperature_path.relative_to(destination).as_posix(),
                "preview_png": preview_path.relative_to(destination).as_posix(),
                "thermal_json": metadata_path.relative_to(destination).as_posix(),
                "statistics": statistics,
                "width": decoded.width,
                "height": decoded.height,
                "sdk_label": decoded.sdk_label,
                "measurement_mode": decoded.measurement_mode,
            }
        )

    manifest = {
        "schema_version": 1,
        "contract": RESULT_CONTRACT,
        "workflow": "THERMOGRAM",
        "platform": "M3T",
        "job_id": handoff.get("job_id"),
        "source_handoff_schema": schema_version,
        "capture_group_count": len(results),
        "capture_groups": results,
    }
    manifest_path = destination / "result-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest
