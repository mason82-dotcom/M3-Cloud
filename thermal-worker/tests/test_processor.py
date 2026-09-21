from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import tifffile
from PIL import Image

from thermal_worker.dji_sdk import DecodeResult, MeasurementParams
from thermal_worker.processor import (
    REGISTRATION_AUDIT_CONTRACT,
    RESULT_CONTRACT,
    _existing_manifest,
    _source_path,
    process_handoff,
)


class FakeDecoder:
    def __init__(self):
        self.paths: list[Path] = []
        self.overrides = None

    def decode_file(self, path, *, overrides=None):
        self.paths.append(Path(path))
        self.overrides = overrides
        return DecodeResult(
            temperature_c=np.array(
                [[20.0, 21.5, 22.0], [23.0, 42.5, 24.0]],
                dtype=np.float32,
            ),
            width=3,
            height=2,
            api_version={"api": 8, "magic": "DIRP"},
            rjpeg_version={"rjpeg": 3, "header": 1, "curve": 1},
            measurement_params=MeasurementParams(
                distance_m=5.0,
                humidity_pct=70.0,
                emissivity=0.95,
                reflection_c=23.0,
                ambient_temp_c=21.0,
            ),
            measurement_ranges={
                "distance_m": {"min": 1.0, "max": 500.0},
                "humidity_pct": {"min": 0.0, "max": 100.0},
                "emissivity": {"min": 0.1, "max": 1.0},
                "reflection_c": {"min": -40.0, "max": 500.0},
                "ambient_temp_c": {"min": -40.0, "max": 500.0},
            },
            measurement_mode="sdk_native",
            measurement_error_code=None,
            sdk_label="test-sdk",
            measurement_abi="AMBIENT_V2",
            sdk_library_name="libdirp.so",
            sdk_library_sha256="c" * 64,
        )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_process_handoff_writes_float_temperature_preview_and_provenance(tmp_path):
    source = tmp_path / "media" / "M3T" / "site" / "nested"
    source.mkdir(parents=True)
    wide = source / "DJI_0001_W.JPG"
    thermal = source / "DJI_0001_T.JPG"
    wide.write_bytes(b"wide-original")
    thermal.write_bytes(b"radiometric-original")

    input_root = tmp_path / "media" / "M3T" / "site"
    handoff = {
        "schema_version": 3,
        "worker_contract": "M3T_RJPEG_V1",
        "workflow": "THERMOGRAM",
        "platform": "M3T",
        "job_id": "22222222-2222-2222-2222-222222222222",
        "external_path": str(input_root),
        "capture_groups": [
            {
                "capture_group": "M3T/site/nested/DJI_0001",
                "files": [
                    {
                        "media_kind": "WIDE",
                        "relative_path": "M3T/site/nested/DJI_0001_W.JPG",
                        "path_relative_to_input": "nested/DJI_0001_W.JPG",
                        "filename": wide.name,
                        "size_bytes": wide.stat().st_size,
                        "sha256": _sha(wide),
                        "capture_time_utc": "2026-09-21T01:02:03+00:00",
                        "metadata": {
                            "camera": {
                                "make": "DJI",
                                "model": "M3T",
                            },
                            "gps": {
                                "latitude": 49.123456,
                                "longitude": 8.654321,
                                "altitude_m": 145.2,
                            },
                        },
                    },
                    {
                        "media_kind": "THERMAL",
                        "relative_path": "M3T/site/nested/DJI_0001_T.JPG",
                        "path_relative_to_input": "nested/DJI_0001_T.JPG",
                        "filename": thermal.name,
                        "size_bytes": thermal.stat().st_size,
                        "sha256": _sha(thermal),
                        "capture_time_utc": "2026-09-21T01:02:03+00:00",
                        "metadata": {
                            "camera": {
                                "make": "DJI",
                                "model": "M3T",
                            },
                            "image": {
                                "width": 3,
                                "height": 2,
                            },
                            "gps": {
                                "latitude": 49.123456,
                                "longitude": 8.654321,
                                "altitude_m": 145.2,
                            },
                        },
                    },
                ],
            }
        ],
    }
    handoff_path = tmp_path / "handoff.json"
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
    output = tmp_path / "results"
    decoder = FakeDecoder()

    manifest = process_handoff(
        handoff_path,
        output,
        decoder,
        measurement_overrides={"emissivity": 0.95},
    )

    assert manifest["contract"] == RESULT_CONTRACT
    assert manifest["capture_group_count"] == 1
    assert manifest["source_identity"]["expected_platform"] == "M3T"
    assert manifest["source_identity"]["confirmed_capture_count"] == 1
    assert manifest["source_identity"]["unconfirmed_capture_count"] == 0
    assert manifest["decoder_provenance"] == {
        "decoder": "DJI_DIRP",
        "sdk_label": "test-sdk",
        "sdk_library_name": "libdirp.so",
        "sdk_library_sha256": "c" * 64,
        "measurement_abi": "AMBIENT_V2",
        "api_version": {"api": 8, "magic": "DIRP"},
    }
    assert decoder.paths == [thermal]
    assert decoder.overrides == {"emissivity": 0.95}

    result = manifest["capture_groups"][0]
    temperature_path = output / result["temperature_tif"]
    preview_path = output / result["preview_png"]
    metadata_path = output / result["thermal_json"]
    hotspot_mask_path = output / result["hotspot_mask_png"]
    hotspots_path = output / result["hotspots_json"]

    temperature_data = tifffile.imread(temperature_path)
    assert temperature_data.dtype == np.float32
    assert temperature_data.shape == (2, 3)
    assert temperature_data[1, 1] == np.float32(42.5)
    with tifffile.TiffFile(temperature_path) as tiff:
        embedded = json.loads(tiff.pages[0].description)
    assert embedded["unit"] == "degree_Celsius"
    assert embedded["api_version"] == {"api": 8, "magic": "DIRP"}
    assert embedded["rjpeg_version"] == {"rjpeg": 3, "header": 1, "curve": 1}
    assert embedded["measurement_abi"] == "AMBIENT_V2"
    assert embedded["sdk_library_name"] == "libdirp.so"
    assert embedded["sdk_library_sha256"] == "c" * 64
    assert embedded["georeferenced"] is False

    with Image.open(preview_path) as preview:
        assert preview.mode == "L"
        assert preview.size == (3, 2)
    with Image.open(hotspot_mask_path) as mask:
        assert mask.mode == "L"
        assert mask.size == (3, 2)
    hotspots = json.loads(hotspots_path.read_text(encoding="utf-8"))
    assert hotspots["diagnostic_scope"] == "HOTSPOT_CANDIDATES_ONLY"
    assert hotspots["component_count"] == 0
    assert hotspots["candidate_pixels"] == 1

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["radiometry"]["unit"] == "degree_Celsius"
    assert metadata["radiometry"]["statistics"]["max_c"] == 42.5
    assert metadata["radiometry"]["measurement_abi"] == "AMBIENT_V2"
    assert metadata["radiometry"]["sdk_library_name"] == "libdirp.so"
    assert metadata["radiometry"]["sdk_library_sha256"] == "c" * 64
    assert metadata["radiometry"]["measurement_ranges"]["distance_m"] == {
        "min": 1.0,
        "max": 500.0,
    }
    assert metadata["radiometry"]["api_version"] == {"api": 8, "magic": "DIRP"}
    assert metadata["radiometry"]["integrity"]["status"] == "PASS"
    assert metadata["radiometry"]["integrity"]["flags"] == []
    assert metadata["radiometry"]["integrity"]["decoded_width"] == 3
    assert metadata["radiometry"]["integrity"]["decoded_height"] == 2
    assert metadata["radiometry"]["integrity"]["source_image_width"] == 3
    assert metadata["radiometry"]["integrity"]["source_image_height"] == 2
    assert manifest["capture_groups"][0]["api_version"] == {"api": 8, "magic": "DIRP"}
    assert manifest["capture_groups"][0]["sdk_library_name"] == "libdirp.so"
    assert manifest["capture_groups"][0]["sdk_library_sha256"] == "c" * 64
    assert manifest["capture_groups"][0]["radiometry_integrity"]["status"] == "PASS"
    assert metadata["analysis"]["hotspots"]["diagnostic_scope"] == "HOTSPOT_CANDIDATES_ONLY"
    assert metadata["source_identity"]["status"] == "CONFIRMED"
    assert result["source_identity"]["status"] == "CONFIRMED"
    assert metadata["registration"]["status"] == "NOT_REGISTERED"
    assert metadata["registration"]["wide_thermal_coregistered"] is False
    assert metadata["registration"]["georeferenced_temperature_raster"] is False
    assert metadata["registration"]["pair_audit"]["capture_time_delta_ms"] == 0.0
    assert metadata["registration"]["pair_audit"]["gps_separation_m"] == pytest.approx(0.0)
    assert result["registration"]["status"] == "NOT_REGISTERED"
    assert result["registration"]["wide_thermal_coregistered"] is False
    assert (output / "result-manifest.json").is_file()
    registration_audit_path = output / manifest["registration_audit_json"]
    registration_audit = json.loads(
        registration_audit_path.read_text(encoding="utf-8")
    )
    assert registration_audit["contract"] == REGISTRATION_AUDIT_CONTRACT
    assert registration_audit["status"] == "NOT_REGISTERED"
    assert registration_audit["pair_count"] == 1
    assert registration_audit["pairs"][0]["capture_group"] == (
        "M3T/site/nested/DJI_0001"
    )
    assert registration_audit["pairs"][0]["pair_audit"][
        "capture_time_delta_ms"
    ] == 0.0
    assert registration_audit["pairs"][0]["pair_audit"][
        "gps_separation_m"
    ] == pytest.approx(0.0)
    assert registration_audit["pairs"][0][
        "wide_thermal_coregistered"
    ] is False
    capture_points_path = output / manifest["capture_points_geojson"]
    capture_points = json.loads(capture_points_path.read_text(encoding="utf-8"))
    assert manifest["georeferenced_capture_count"] == 1
    assert capture_points["metadata"]["geometry_scope"] == "CAPTURE_CENTER_ONLY"
    feature = capture_points["features"][0]
    assert feature["geometry"] == {
        "type": "Point",
        "coordinates": [8.654321, 49.123456],
    }
    assert feature["properties"]["position_source"] == "THERMAL"
    assert feature["properties"]["pixel_georeferenced"] is False
    assert feature["properties"]["max_c"] == 42.5
    assert feature["properties"]["hotspot_component_count"] == 0

    summary_json = json.loads(
        (output / manifest["summary_json"]).read_text(encoding="utf-8")
    )
    assert summary_json["decoder_provenance"] == manifest["decoder_provenance"]
    assert summary_json["aggregate"]["capture_count"] == 1
    assert summary_json["aggregate"]["georeferenced_capture_count"] == 1
    assert summary_json["aggregate"]["max_c"] == 42.5
    assert summary_json["aggregate"]["hotspot_component_count"] == 0
    assert summary_json["aggregate"]["radiometry_warning_capture_count"] == 0
    assert summary_json["aggregate"]["m3t_identity_confirmed_count"] == 1
    assert summary_json["aggregate"]["m3t_identity_unconfirmed_count"] == 0
    assert summary_json["captures"][0]["source_identity_status"] == "CONFIRMED"
    assert summary_json["aggregate"]["registration_status"] == "NOT_REGISTERED"
    assert summary_json["aggregate"]["pair_capture_time_evidence_count"] == 1
    assert summary_json["aggregate"]["pair_gps_evidence_count"] == 1
    assert summary_json["captures"][0]["registration_status"] == "NOT_REGISTERED"
    assert summary_json["captures"][0]["pair_capture_time_delta_ms"] == 0.0
    assert summary_json["captures"][0]["pair_gps_separation_m"] == pytest.approx(0.0)
    summary_csv = (output / manifest["summary_csv"]).read_text(encoding="utf-8")
    assert "capture_group,capture_time_utc,latitude,longitude" in summary_csv
    assert "source_identity_status" in summary_csv
    assert "registration_status" in summary_csv
    assert "pair_capture_time_delta_ms" in summary_csv
    assert "pair_gps_separation_m" in summary_csv
    assert "M3T/site/nested/DJI_0001" in summary_csv
    assert "NOT_REGISTERED" in summary_csv
    assert len(manifest["input_fingerprint"]) == 64

    retry_decoder = FakeDecoder()
    retried = process_handoff(
        handoff_path,
        output,
        retry_decoder,
        measurement_overrides={"emissivity": 0.95},
    )
    assert retried == manifest
    assert retry_decoder.paths == []


def test_process_handoff_rejects_changed_frozen_input(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    wide = source / "DJI_0001_W.JPG"
    thermal = source / "DJI_0001_T.JPG"
    wide.write_bytes(b"wide")
    thermal.write_bytes(b"thermal")

    handoff = {
        "schema_version": 3,
        "worker_contract": "M3T_RJPEG_V1",
        "workflow": "THERMOGRAM",
        "platform": "M3T",
        "job_id": "job",
        "external_path": str(source),
        "capture_groups": [
            {
                "capture_group": "M3T/site/DJI_0001",
                "files": [
                    {
                        "media_kind": "WIDE",
                        "path_relative_to_input": wide.name,
                        "filename": wide.name,
                        "size_bytes": wide.stat().st_size,
                        "sha256": _sha(wide),
                    },
                    {
                        "media_kind": "THERMAL",
                        "path_relative_to_input": thermal.name,
                        "filename": thermal.name,
                        "size_bytes": thermal.stat().st_size,
                        "sha256": "0" * 64,
                    },
                ],
            }
        ],
    }
    handoff_path = tmp_path / "handoff.json"
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")

    output = tmp_path / "out"
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        process_handoff(handoff_path, output, FakeDecoder())

    assert not output.exists()
    assert not list(tmp_path.glob(".out.staging-*"))

def test_hotspot_analysis_reports_connected_candidate_regions():
    from thermal_worker.processor import _hotspot_analysis

    temperature = np.full((6, 8), 20.0, dtype=np.float32)
    temperature[2:4, 3:6] = np.array(
        [[31.0, 33.0, 32.0], [30.5, 42.0, 31.5]],
        dtype=np.float32,
    )

    analysis, mask = _hotspot_analysis(
        temperature,
        delta_c=10.0,
        min_pixels=4,
    )

    assert analysis["baseline_c"] == 20.0
    assert analysis["threshold_c"] == 30.0
    assert analysis["component_count"] == 1
    candidate = analysis["components"][0]
    assert candidate["pixel_count"] == 6
    assert candidate["max_c"] == 42.0
    assert candidate["peak_x_px"] == 4
    assert candidate["peak_y_px"] == 3
    assert np.count_nonzero(mask) == 6


def test_changed_processing_options_do_not_reuse_existing_results(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    wide = source / "DJI_0001_W.JPG"
    thermal = source / "DJI_0001_T.JPG"
    wide.write_bytes(b"wide")
    thermal.write_bytes(b"thermal")
    handoff = {
        "schema_version": 3,
        "worker_contract": "M3T_RJPEG_V1",
        "workflow": "THERMOGRAM",
        "platform": "M3T",
        "job_id": "job-options",
        "input_prefix": "M3T/site",
        "external_path": str(source),
        "capture_groups": [
            {
                "capture_group": "M3T/site/DJI_0001",
                "files": [
                    {
                        "media_kind": "WIDE",
                        "path_relative_to_input": wide.name,
                        "filename": wide.name,
                        "size_bytes": wide.stat().st_size,
                        "sha256": _sha(wide),
                    },
                    {
                        "media_kind": "THERMAL",
                        "path_relative_to_input": thermal.name,
                        "filename": thermal.name,
                        "size_bytes": thermal.stat().st_size,
                        "sha256": _sha(thermal),
                    },
                ],
            }
        ],
    }
    handoff_path = tmp_path / "handoff.json"
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
    output = tmp_path / "out"

    process_handoff(
        handoff_path,
        output,
        FakeDecoder(),
        hotspot_delta_c=10.0,
    )
    with pytest.raises(FileExistsError, match="do not match"):
        process_handoff(
            handoff_path,
            output,
            FakeDecoder(),
            hotspot_delta_c=5.0,
        )

def test_hotspot_mask_excludes_small_island_inside_retained_component_bbox():
    from thermal_worker.processor import _hotspot_analysis

    temperature = np.full((7, 7), 20.0, dtype=np.float32)
    # One retained U-shaped component with a large bounding box.
    for y, x in [
        (1, 1), (2, 1), (3, 1), (4, 1), (5, 1),
        (5, 2), (5, 3), (5, 4), (5, 5),
        (4, 5), (3, 5), (2, 5), (1, 5),
    ]:
        temperature[y, x] = 35.0
    # A single hot pixel lies inside that bounding box but is disconnected and
    # must be filtered by min_pixels rather than painted back into the mask.
    temperature[3, 3] = 40.0

    analysis, mask = _hotspot_analysis(
        temperature,
        delta_c=10.0,
        min_pixels=4,
    )

    assert analysis["candidate_pixels"] == 14
    assert analysis["retained_pixels"] == 13
    assert analysis["filtered_pixels"] == 1
    assert analysis["component_count"] == 1
    assert mask[3, 3] == 0
    assert np.count_nonzero(mask) == 13

def test_source_path_rejects_symlink_escape(tmp_path):
    source_root = tmp_path / "media"
    source_root.mkdir()
    outside = tmp_path / "outside-rjpeg.JPG"
    outside.write_bytes(b"outside")
    link = source_root / "DJI_0001_T.JPG"
    link.symlink_to(outside)

    with pytest.raises(ValueError, match="escapes external_path"):
        _source_path(
            source_root,
            {"path_relative_to_input": link.name},
        )


def test_existing_manifest_rejects_intermediate_symlink_escape(tmp_path):
    destination = tmp_path / "results"
    destination.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "artifact.bin").write_bytes(b"external")

    for name in ("capture-points.geojson", "thermal-summary.json", "thermal-summary.csv"):
        (destination / name).write_bytes(b"root-artifact")

    captures = destination / "captures"
    captures.symlink_to(outside, target_is_directory=True)
    artifact_path = "captures/artifact.bin"
    manifest = {
        "contract": RESULT_CONTRACT,
        "job_id": "job",
        "input_fingerprint": "f" * 64,
        "capture_points_geojson": "capture-points.geojson",
        "summary_json": "thermal-summary.json",
        "summary_csv": "thermal-summary.csv",
        "capture_groups": [
            {
                "temperature_tif": artifact_path,
                "preview_png": artifact_path,
                "thermal_json": artifact_path,
                "hotspot_mask_png": artifact_path,
                "hotspots_json": artifact_path,
            }
        ],
    }
    (destination / "result-manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError, match="escapes result folder"):
        _existing_manifest(
            destination,
            expected_job_id="job",
            expected_fingerprint="f" * 64,
        )

def test_capture_point_falls_back_to_wide_gps_without_georeferencing_pixels():
    from thermal_worker.processor import _capture_point_feature

    feature = _capture_point_feature(
        capture_group="M3T/site/DJI_0001",
        thermal_item={"filename": "DJI_0001_T.JPG", "metadata": {"gps": {}}},
        wide_item={
            "filename": "DJI_0001_W.JPG",
            "capture_time_utc": "2026-09-21T01:02:03+00:00",
            "metadata": {
                "gps": {
                    "latitude": 49.2,
                    "longitude": 8.5,
                }
            },
        },
        statistics={"min_c": 20.0, "max_c": 42.0, "mean_c": 24.0},
        hotspot_analysis={
            "component_count": 1,
            "components": [{"max_c": 42.0, "delta_max_c": 18.0}],
        },
    )

    assert feature["geometry"]["coordinates"] == [8.5, 49.2]
    assert feature["properties"]["position_source"] == "WIDE"
    assert feature["properties"]["position_scope"] == "CAPTURE_CENTER_ONLY"
    assert feature["properties"]["pixel_georeferenced"] is False
    assert feature["properties"]["hotspot_peak_delta_c"] == 18.0

def test_existing_manifest_rejects_root_artifact_parent_symlink_escape(tmp_path):
    destination = tmp_path / "results"
    destination.mkdir()
    outside = tmp_path / "outside-root"
    outside.mkdir()
    (outside / "capture-points.geojson").write_bytes(b"external")

    linked = destination / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    (destination / "thermal-summary.json").write_bytes(b"{}")
    (destination / "thermal-summary.csv").write_bytes(b"header\n")

    captures = destination / "captures"
    captures.mkdir()
    for name in (
        "temperature.tif",
        "preview.png",
        "thermal.json",
        "hotspot-mask.png",
        "hotspots.json",
    ):
        (captures / name).write_bytes(b"artifact")

    manifest = {
        "contract": RESULT_CONTRACT,
        "job_id": "job-root",
        "input_fingerprint": "e" * 64,
        "capture_points_geojson": "linked/capture-points.geojson",
        "summary_json": "thermal-summary.json",
        "summary_csv": "thermal-summary.csv",
        "capture_groups": [
            {
                "temperature_tif": "captures/temperature.tif",
                "preview_png": "captures/preview.png",
                "thermal_json": "captures/thermal.json",
                "hotspot_mask_png": "captures/hotspot-mask.png",
                "hotspots_json": "captures/hotspots.json",
            }
        ],
    }
    (destination / "result-manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError, match="escapes result folder"):
        _existing_manifest(
            destination,
            expected_job_id="job-root",
            expected_fingerprint="e" * 64,
        )

def test_radiometry_integrity_warns_only_on_structural_decode_provenance_issues():
    from thermal_worker.processor import _radiometry_integrity

    decoded = DecodeResult(
        temperature_c=np.array([[20.0, np.nan]], dtype=np.float32),
        width=2,
        height=1,
        api_version={"api": 8, "magic": "DIRP"},
        rjpeg_version={"rjpeg": 3, "header": 1, "curve": 1},
        measurement_params=None,
        measurement_ranges=None,
        measurement_mode="sdk_native_unreadable",
        measurement_error_code=-3,
        sdk_label="test-sdk",
        measurement_abi="UNKNOWN",
    )
    quality = _radiometry_integrity(
        decoded,
        {
            "finite_pixels": 1,
            "invalid_pixels": 1,
        },
    )

    assert quality["status"] == "WARN"
    assert quality["finite_fraction"] == 0.5
    assert quality["invalid_fraction"] == 0.5
    assert quality["flags"] == [
        "INVALID_TEMPERATURE_PIXELS",
        "MEASUREMENT_PARAMS_UNREADABLE",
        "MEASUREMENT_ABI_UNCONFIRMED",
    ]
    assert "defect assessment" in quality["note"]

def test_radiometry_integrity_flags_skipped_api_version_query():
    from thermal_worker.processor import _radiometry_integrity

    decoded = DecodeResult(
        temperature_c=np.array([[20.0]], dtype=np.float32),
        width=1,
        height=1,
        api_version={
            "api": 0,
            "magic": "UNKNOWN",
            "query_status": "SKIPPED_UNCONFIRMED_ABI",
        },
        rjpeg_version={"rjpeg": 3, "header": 1, "curve": 1},
        measurement_params=MeasurementParams(
            distance_m=5.0,
            humidity_pct=70.0,
            emissivity=0.95,
            reflection_c=23.0,
            ambient_temp_c=21.0,
        ),
        measurement_ranges=None,
        measurement_mode="sdk_native",
        measurement_error_code=None,
        sdk_label="headerless-sdk",
        measurement_abi="AMBIENT_V2",
    )

    quality = _radiometry_integrity(
        decoded,
        {
            "finite_pixels": 1,
            "invalid_pixels": 0,
        },
    )

    assert quality["status"] == "WARN"
    assert quality["flags"] == ["API_VERSION_ABI_UNCONFIRMED"]
    assert (
        quality["api_version_query_status"]
        == "SKIPPED_UNCONFIRMED_ABI"
    )

def test_radiometry_integrity_flags_frozen_metadata_dimension_mismatch():
    from thermal_worker.processor import _radiometry_integrity

    decoded = DecodeResult(
        temperature_c=np.zeros((512, 640), dtype=np.float32),
        width=640,
        height=512,
        api_version={"api": 8, "magic": "DIRP"},
        rjpeg_version={"rjpeg": 3, "header": 1, "curve": 1},
        measurement_params=MeasurementParams(
            distance_m=5.0,
            humidity_pct=70.0,
            emissivity=0.95,
            reflection_c=23.0,
            ambient_temp_c=21.0,
        ),
        measurement_ranges=None,
        measurement_mode="sdk_native",
        measurement_error_code=None,
        sdk_label="test-sdk",
        measurement_abi="AMBIENT_V2",
    )

    quality = _radiometry_integrity(
        decoded,
        {
            "finite_pixels": 640 * 512,
            "invalid_pixels": 0,
        },
        source_metadata={
            "image": {
                "width": 1280,
                "height": 1024,
            }
        },
    )

    assert quality["status"] == "WARN"
    assert quality["flags"] == ["SOURCE_DIMENSION_MISMATCH"]
    assert quality["decoded_width"] == 640
    assert quality["decoded_height"] == 512
    assert quality["source_image_width"] == 1280
    assert quality["source_image_height"] == 1024

def test_registration_audit_compares_pair_metadata_without_registering_pixels():
    from thermal_worker.processor import _registration_audit

    wide = {
        "capture_time_utc": "2026-09-21T01:02:03.000000+00:00",
        "metadata": {
            "gps": {
                "latitude": 49.1,
                "longitude": 8.5,
                "altitude_m": 145.0,
            },
            "dji_altitude": {
                "absolute_ellipsoid_m": 145.5,
                "relative_takeoff_m": 60.0,
            },
            "flight_attitude": {
                "yaw_deg": 178.0,
                "pitch_deg": 2.0,
                "roll_deg": -1.0,
            },
            "gimbal_attitude": {
                "yaw_deg": 179.0,
                "pitch_deg": -90.0,
                "roll_deg": 0.2,
            },
            "image": {
                "width": 5280,
                "height": 3956,
                "focal_length_mm": 12.29,
                "focal_length_35mm": 24.0,
            },
            "raw": {
                "xmp": {
                    "drone-dji": {
                        "CalibratedFocalLength": "12000.000000",
                        "CalibratedOpticalCenterX": "2640.000000",
                        "CalibratedOpticalCenterY": "1978.000000",
                    }
                }
            },
        },
    }
    thermal = {
        "capture_time_utc": "2026-09-21T01:02:03.025000+00:00",
        "metadata": {
            "gps": {
                "latitude": 49.1,
                "longitude": 8.5,
                "altitude_m": 145.2,
            },
            "dji_altitude": {
                "absolute_ellipsoid_m": 145.7,
                "relative_takeoff_m": 60.2,
            },
            "flight_attitude": {
                "yaw_deg": -179.0,
                "pitch_deg": 1.5,
                "roll_deg": -0.4,
            },
            "gimbal_attitude": {
                "yaw_deg": -179.0,
                "pitch_deg": -89.0,
                "roll_deg": -0.1,
            },
            "image": {
                "width": 640,
                "height": 512,
                "focal_length_mm": 9.1,
                "focal_length_35mm": 40.0,
            },
            "raw": {
                "xmp": {
                    "drone-dji": {
                        "CalibratedFocalLength": "9100.000000",
                        "CalibratedOpticalCenterX": "0.000000",
                        "CalibratedOpticalCenterY": "0.000000",
                    }
                }
            },
        },
    }

    audit = _registration_audit(wide, thermal)

    assert audit["status"] == "NOT_REGISTERED"
    assert audit["wide_thermal_coregistered"] is False
    assert audit["georeferenced_temperature_raster"] is False
    pair = audit["pair_audit"]
    assert pair["capture_time_delta_ms"] == pytest.approx(25.0)
    assert pair["gps_separation_m"] == pytest.approx(0.0)
    assert pair["gimbal_delta_deg"]["yaw_deg"] == pytest.approx(2.0)
    assert pair["gimbal_delta_deg"]["pitch_deg"] == pytest.approx(1.0)
    assert pair["gimbal_delta_deg"]["roll_deg"] == pytest.approx(0.3)
    assert pair["flight_attitude_delta_deg"] == {
        "yaw_deg": pytest.approx(3.0),
        "pitch_deg": pytest.approx(0.5),
        "roll_deg": pytest.approx(0.6),
    }
    assert pair["altitude_delta_m"]["absolute_ellipsoid_m"] == pytest.approx(0.2)
    assert pair["altitude_delta_m"]["relative_takeoff_m"] == pytest.approx(0.2)
    assert pair["altitude_delta_m"]["gps_altitude_m"] == pytest.approx(0.2)
    assert pair["wide_image"] == {
        "width": 5280,
        "height": 3956,
        "focal_length_mm": pytest.approx(12.29),
        "focal_length_35mm": pytest.approx(24.0),
    }
    assert pair["thermal_image"] == {
        "width": 640,
        "height": 512,
        "focal_length_mm": pytest.approx(9.1),
        "focal_length_35mm": pytest.approx(40.0),
    }
    assert pair["wide_dji_calibration_raw"]["CalibratedFocalLength"] == "12000.000000"
    assert pair["thermal_dji_calibration_raw"] == {
        "CalibratedFocalLength": "9100.000000",
        "CalibratedOpticalCenterX": "0.000000",
        "CalibratedOpticalCenterY": "0.000000",
    }
    assert pair["evidence"] == {
        "capture_time_pair": True,
        "gps_pair": True,
        "gimbal_attitude_pair": True,
        "flight_attitude_pair": True,
        "dji_altitude_pair": True,
        "wide_image_dimensions": True,
        "thermal_image_dimensions": True,
        "wide_dji_calibration": True,
        "thermal_dji_calibration": True,
    }
    assert "does not establish registration" in audit["note"]
    assert audit["status"] == "NOT_REGISTERED"


def test_registration_audit_leaves_missing_pair_evidence_unknown():
    from thermal_worker.processor import _registration_audit

    audit = _registration_audit(
        {"metadata": {}},
        {"metadata": {}},
    )

    assert audit["status"] == "NOT_REGISTERED"
    pair = audit["pair_audit"]
    assert pair["capture_time_delta_ms"] is None
    assert pair["gps_separation_m"] is None
    assert pair["gimbal_delta_deg"] == {
        "yaw_deg": None,
        "pitch_deg": None,
        "roll_deg": None,
    }
    assert pair["flight_attitude_delta_deg"] == {
        "yaw_deg": None,
        "pitch_deg": None,
        "roll_deg": None,
    }
    assert pair["altitude_delta_m"] == {
        "absolute_ellipsoid_m": None,
        "relative_takeoff_m": None,
        "gps_altitude_m": None,
    }
    assert pair["wide_image"] == {
        "width": None,
        "height": None,
        "focal_length_mm": None,
        "focal_length_35mm": None,
    }
    assert pair["thermal_image"] == pair["wide_image"]
    assert pair["wide_dji_calibration_raw"] == {}
    assert pair["thermal_dji_calibration_raw"] == {}
    assert not any(pair["evidence"].values())

def test_process_handoff_rejects_decoder_provenance_change_between_captures(
    tmp_path,
):
    class ChangingDecoder(FakeDecoder):
        def decode_file(self, path, *, overrides=None):
            result = super().decode_file(path, overrides=overrides)
            if len(self.paths) == 2:
                return DecodeResult(
                    temperature_c=result.temperature_c,
                    width=result.width,
                    height=result.height,
                    api_version=result.api_version,
                    rjpeg_version=result.rjpeg_version,
                    measurement_params=result.measurement_params,
                    measurement_ranges=result.measurement_ranges,
                    measurement_mode=result.measurement_mode,
                    measurement_error_code=result.measurement_error_code,
                    sdk_label=result.sdk_label,
                    measurement_abi=result.measurement_abi,
                    sdk_library_name=result.sdk_library_name,
                    sdk_library_sha256="e" * 64,
                )
            return result

    source = tmp_path / "input"
    source.mkdir()
    groups = []
    for index in (1, 2):
        wide = source / f"DJI_{index:04d}_W.JPG"
        thermal = source / f"DJI_{index:04d}_T.JPG"
        wide.write_bytes(f"wide-{index}".encode())
        thermal.write_bytes(f"thermal-{index}".encode())
        groups.append(
            {
                "capture_group": f"M3T/site/DJI_{index:04d}",
                "files": [
                    {
                        "media_kind": "WIDE",
                        "path_relative_to_input": wide.name,
                        "filename": wide.name,
                        "size_bytes": wide.stat().st_size,
                        "sha256": _sha(wide),
                    },
                    {
                        "media_kind": "THERMAL",
                        "path_relative_to_input": thermal.name,
                        "filename": thermal.name,
                        "size_bytes": thermal.stat().st_size,
                        "sha256": _sha(thermal),
                    },
                ],
            }
        )

    handoff = {
        "schema_version": 3,
        "worker_contract": "M3T_RJPEG_V1",
        "workflow": "THERMOGRAM",
        "platform": "M3T",
        "job_id": "job-decoder-change",
        "external_path": str(source),
        "capture_groups": groups,
    }
    handoff_path = tmp_path / "handoff.json"
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="decoder provenance changed",
    ):
        process_handoff(
            handoff_path,
            tmp_path / "results",
            ChangingDecoder(),
        )

    assert not (tmp_path / "results").exists()

def test_m3t_source_identity_keeps_unknown_model_unconfirmed():
    from thermal_worker.processor import _m3t_source_identity

    identity = _m3t_source_identity(
        {"metadata": {"camera": {"model": "FC3582"}}},
        {"metadata": {"camera": {"model": "DJI-THERMAL-SENSOR"}}},
    )

    assert identity["status"] == "UNCONFIRMED"
    assert identity["wide"]["known_conflict"] is False
    assert identity["thermal"]["known_conflict"] is False


@pytest.mark.parametrize(
    "model",
    [
        "M30T",
        "H30T",
        "M4T",
        "M3TD",
        "Mavic 3 Enterprise",
        "Mavic 3 Multispectral",
    ],
)
def test_m3t_source_identity_rejects_known_other_dji_models(model):
    from thermal_worker.processor import _require_m3t_source_identity

    with pytest.raises(ValueError, match="conflicts with M3T-only"):
        _require_m3t_source_identity(
            "M3T/site/DJI_0001",
            {"metadata": {"camera": {"model": "M3T"}}},
            {"metadata": {"camera": {"model": model}}},
        )


def test_m3t_source_identity_accepts_common_m3t_aliases():
    from thermal_worker.processor import _m3t_source_identity

    for model in ("M3T", "Mavic 3T", "Mavic 3 Thermal", "DJI Mavic 3 Thermal"):
        identity = _m3t_source_identity(
            {"metadata": {}},
            {"metadata": {"camera": {"model": model}}},
        )
        assert identity["status"] == "CONFIRMED"
        assert identity["thermal"]["m3t_confirmed"] is True

