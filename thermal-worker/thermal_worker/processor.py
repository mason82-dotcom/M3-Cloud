from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
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
    short_hash = hashlib.sha256(capture_group.encode("utf-8")).hexdigest()[:10]
    return f"{index:05d}_{safe}_{short_hash}"


def _hotspot_analysis(
    temperature: np.ndarray,
    *,
    delta_c: float,
    min_pixels: int,
) -> tuple[dict[str, Any], np.ndarray]:
    if not math.isfinite(delta_c) or delta_c <= 0:
        raise ValueError("hotspot_delta_c must be finite and greater than zero")
    if min_pixels < 1:
        raise ValueError("hotspot_min_pixels must be at least 1")

    finite_mask = np.isfinite(temperature)
    finite = temperature[finite_mask]
    if finite.size == 0:
        raise ValueError("Temperature plane contains no finite samples")

    baseline_c = float(np.median(finite))
    threshold_c = baseline_c + float(delta_c)
    candidate_mask = finite_mask & (temperature >= threshold_c)
    visited = np.zeros(candidate_mask.shape, dtype=np.bool_)
    height, width = candidate_mask.shape
    components: list[dict[str, Any]] = []

    for y0, x0 in np.argwhere(candidate_mask):
        y0 = int(y0)
        x0 = int(x0)
        if visited[y0, x0]:
            continue
        stack = [(y0, x0)]
        visited[y0, x0] = True
        pixels: list[tuple[int, int]] = []
        while stack:
            y, x = stack.pop()
            pixels.append((y, x))
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if (
                    0 <= ny < height
                    and 0 <= nx < width
                    and candidate_mask[ny, nx]
                    and not visited[ny, nx]
                ):
                    visited[ny, nx] = True
                    stack.append((ny, nx))

        if len(pixels) < min_pixels:
            continue
        ys = np.fromiter((point[0] for point in pixels), dtype=np.int32)
        xs = np.fromiter((point[1] for point in pixels), dtype=np.int32)
        values = temperature[ys, xs]
        max_index = int(np.argmax(values))
        components.append(
            {
                "pixel_count": int(len(pixels)),
                "max_c": float(values[max_index]),
                "mean_c": float(np.mean(values)),
                "delta_max_c": float(values[max_index] - baseline_c),
                "centroid_x_px": float(np.mean(xs)),
                "centroid_y_px": float(np.mean(ys)),
                "peak_x_px": int(xs[max_index]),
                "peak_y_px": int(ys[max_index]),
                "bbox": {
                    "x_min": int(np.min(xs)),
                    "y_min": int(np.min(ys)),
                    "x_max": int(np.max(xs)),
                    "y_max": int(np.max(ys)),
                },
            }
        )

    components.sort(key=lambda item: float(item["max_c"]), reverse=True)
    kept_mask = np.zeros(candidate_mask.shape, dtype=np.uint8)
    for component in components:
        bbox = component["bbox"]
        y_slice = slice(int(bbox["y_min"]), int(bbox["y_max"]) + 1)
        x_slice = slice(int(bbox["x_min"]), int(bbox["x_max"]) + 1)
        window = candidate_mask[y_slice, x_slice]
        kept_mask[y_slice, x_slice][window] = 255

    candidate_pixels = int(np.count_nonzero(candidate_mask))
    return (
        {
            "method": "GLOBAL_MEDIAN_DELTA_CONNECTED_4",
            "diagnostic_scope": "HOTSPOT_CANDIDATES_ONLY",
            "baseline_c": baseline_c,
            "delta_threshold_c": float(delta_c),
            "threshold_c": threshold_c,
            "min_component_pixels": int(min_pixels),
            "candidate_pixels": candidate_pixels,
            "candidate_fraction": float(candidate_pixels / finite.size),
            "component_count": len(components),
            "components": components[:100],
            "components_truncated": len(components) > 100,
            "note": (
                "Candidates are sensor-space thermal regions above a global median delta. "
                "They are not classified equipment or PV defects."
            ),
        },
        kept_mask,
    )


def _handoff_fingerprint(
    handoff: Mapping[str, Any],
    *,
    processing_options: Mapping[str, Any],
) -> str:
    groups = handoff.get("capture_groups")
    normalized_groups: list[dict[str, Any]] = []
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            files = group.get("files")
            normalized_files = []
            if isinstance(files, list):
                for item in files:
                    if not isinstance(item, Mapping):
                        continue
                    normalized_files.append(
                        {
                            "media_kind": item.get("media_kind"),
                            "path_relative_to_input": item.get("path_relative_to_input"),
                            "relative_path": item.get("relative_path"),
                            "size_bytes": item.get("size_bytes"),
                            "sha256": item.get("sha256"),
                        }
                    )
            normalized_files.sort(
                key=lambda item: (
                    str(item.get("media_kind") or ""),
                    str(item.get("path_relative_to_input") or item.get("relative_path") or ""),
                )
            )
            normalized_groups.append(
                {
                    "capture_group": group.get("capture_group"),
                    "files": normalized_files,
                }
            )
    normalized_groups.sort(key=lambda item: str(item.get("capture_group") or ""))
    payload = {
        "worker_contract": handoff.get("worker_contract"),
        "job_id": handoff.get("job_id"),
        "input_prefix": handoff.get("input_prefix"),
        "capture_groups": normalized_groups,
        "processing_options": processing_options,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _existing_manifest(
    destination: Path,
    *,
    expected_job_id: Any,
    expected_fingerprint: str,
) -> dict[str, Any] | None:
    if not destination.exists():
        return None
    if destination.is_symlink():
        raise FileExistsError(f"Thermal result path must not be a symlink: {destination}")
    if not destination.is_dir():
        raise FileExistsError(f"Thermal result path is not a directory: {destination}")
    if not any(destination.iterdir()):
        return None

    manifest_path = destination / "result-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise FileExistsError(
            f"Thermal result directory is non-empty without a valid manifest: {destination}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FileExistsError(
            f"Thermal result manifest is unreadable: {manifest_path}"
        ) from exc
    if not isinstance(manifest, dict):
        raise FileExistsError(f"Thermal result manifest is not an object: {manifest_path}")
    if (
        manifest.get("contract") != RESULT_CONTRACT
        or manifest.get("job_id") != expected_job_id
        or manifest.get("input_fingerprint") != expected_fingerprint
    ):
        raise FileExistsError(
            f"Existing thermal results do not match this frozen handoff: {destination}"
        )

    groups = manifest.get("capture_groups")
    if not isinstance(groups, list) or not groups:
        raise FileExistsError(f"Existing thermal result manifest has no capture groups: {destination}")
    for group in groups:
        if not isinstance(group, Mapping):
            raise FileExistsError("Existing thermal result manifest has an invalid capture group")
        for key in ("temperature_tif", "preview_png", "thermal_json"):
            relative = group.get(key)
            if not isinstance(relative, str):
                raise FileExistsError(f"Existing thermal result manifest is missing {key}")
            safe = _safe_relative_path(relative)
            artifact = destination.joinpath(*safe.parts)
            if artifact.is_symlink() or not artifact.is_file():
                raise FileExistsError(f"Existing thermal result artifact is missing: {artifact}")
    return manifest


def _write_temperature_tiff(
    path: Path,
    temperature: np.ndarray,
    *,
    source_sha256: str | None,
    sdk_label: str,
    api_version: Mapping[str, int | str],
    rjpeg_version: Mapping[str, int],
    measurement_abi: str,
) -> None:
    description = {
        "schema_version": 1,
        "quantity": "temperature",
        "unit": "degree_Celsius",
        "source_sha256": source_sha256,
        "decoder": "DJI_DIRP",
        "sdk_label": sdk_label,
        "api_version": dict(api_version),
        "rjpeg_version": dict(rjpeg_version),
        "measurement_abi": measurement_abi,
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
    hotspot_delta_c: float = 10.0,
    hotspot_min_pixels: int = 4,
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
    destination_parent = destination.parent
    destination_parent.mkdir(parents=True, exist_ok=True)
    processing_options = {
        "measurement_overrides": dict(measurement_overrides or {}),
        "hotspot_analysis": {
            "delta_c": float(hotspot_delta_c),
            "min_pixels": int(hotspot_min_pixels),
        },
    }
    input_fingerprint = _handoff_fingerprint(
        handoff,
        processing_options=processing_options,
    )
    existing = _existing_manifest(
        destination,
        expected_job_id=handoff.get("job_id"),
        expected_fingerprint=input_fingerprint,
    )
    if existing is not None:
        return existing

    groups = handoff.get("capture_groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("Thermogram handoff contains no capture groups")

    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name or 'thermal-results'}.staging-",
            dir=destination_parent,
        )
    )
    published = False
    try:
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
                raise TypeError(
                    f"Capture group {capture_group} is missing WIDE/THERMAL pair objects"
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
            hotspot_analysis, hotspot_mask = _hotspot_analysis(
                temperature,
                delta_c=hotspot_delta_c,
                min_pixels=hotspot_min_pixels,
            )
            folder = staging / "captures" / _capture_output_name(index, capture_group)
            folder.mkdir(parents=True, exist_ok=True)
            temperature_path = folder / "temperature.tif"
            preview_path = folder / "preview.png"
            hotspot_mask_path = folder / "hotspot-mask.png"
            hotspots_path = folder / "hotspots.json"
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
                api_version=decoded.api_version,
                rjpeg_version=decoded.rjpeg_version,
                measurement_abi=decoded.measurement_abi,
            )
            preview = _preview(temperature, statistics)
            preview.save(preview_path, format="PNG")
            Image.fromarray(hotspot_mask, mode="L").save(
                hotspot_mask_path,
                format="PNG",
            )
            hotspots_path.write_text(
                json.dumps(
                    hotspot_analysis,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
    
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
                    "api_version": decoded.api_version,
                    "rjpeg_version": decoded.rjpeg_version,
                    "width": decoded.width,
                    "height": decoded.height,
                    "dtype": "float32",
                    "unit": "degree_Celsius",
                    "measurement_mode": decoded.measurement_mode,
                    "measurement_abi": decoded.measurement_abi,
                    "measurement_error_code": decoded.measurement_error_code,
                    "measurement_params": (
                        decoded.measurement_params.as_dict()
                        if decoded.measurement_params is not None
                        else None
                    ),
                    "measurement_ranges": decoded.measurement_ranges,
                    "requested_overrides": dict(measurement_overrides or {}),
                    "statistics": statistics,
                },
                "analysis": {
                    "hotspots": hotspot_analysis,
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
                    "temperature_tif": temperature_path.relative_to(staging).as_posix(),
                    "preview_png": preview_path.relative_to(staging).as_posix(),
                    "hotspot_mask_png": hotspot_mask_path.relative_to(staging).as_posix(),
                    "hotspots_json": hotspots_path.relative_to(staging).as_posix(),
                },
            }
            metadata_path.write_text(
                json.dumps(thermal_metadata, indent=2, sort_keys=True, ensure_ascii=False),
                encoding="utf-8",
            )
    
            results.append(
                {
                    "capture_group": capture_group,
                    "temperature_tif": temperature_path.relative_to(staging).as_posix(),
                    "preview_png": preview_path.relative_to(staging).as_posix(),
                    "thermal_json": metadata_path.relative_to(staging).as_posix(),
                    "hotspot_mask_png": hotspot_mask_path.relative_to(staging).as_posix(),
                    "hotspots_json": hotspots_path.relative_to(staging).as_posix(),
                    "statistics": statistics,
                    "hotspots": {
                        "baseline_c": hotspot_analysis["baseline_c"],
                        "threshold_c": hotspot_analysis["threshold_c"],
                        "component_count": hotspot_analysis["component_count"],
                        "candidate_pixels": hotspot_analysis["candidate_pixels"],
                        "candidate_fraction": hotspot_analysis["candidate_fraction"],
                    },
                    "width": decoded.width,
                    "height": decoded.height,
                    "sdk_label": decoded.sdk_label,
                    "api_version": decoded.api_version,
                    "measurement_mode": decoded.measurement_mode,
                    "measurement_abi": decoded.measurement_abi,
                    "measurement_ranges": decoded.measurement_ranges,
                }
            )
    
        manifest = {
            "schema_version": 1,
            "contract": RESULT_CONTRACT,
            "workflow": "THERMOGRAM",
            "platform": "M3T",
            "job_id": handoff.get("job_id"),
            "source_handoff_schema": schema_version,
            "input_fingerprint": input_fingerprint,
            "processing_options": processing_options,
            "capture_group_count": len(results),
            "capture_groups": results,
        }
        manifest_path = staging / "result-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        if destination.exists():
            destination.rmdir()
        os.replace(staging, destination)
        published = True
        return manifest
    finally:
        if not published:
            shutil.rmtree(staging, ignore_errors=True)
