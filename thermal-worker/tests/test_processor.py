from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import tifffile
from PIL import Image

from thermal_worker.dji_sdk import DecodeResult, MeasurementParams
from thermal_worker.processor import RESULT_CONTRACT, process_handoff


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
            measurement_mode="sdk_native",
            measurement_error_code=None,
            sdk_label="test-sdk",
            measurement_abi="AMBIENT_V2",
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
                    },
                    {
                        "media_kind": "THERMAL",
                        "relative_path": "M3T/site/nested/DJI_0001_T.JPG",
                        "path_relative_to_input": "nested/DJI_0001_T.JPG",
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
    assert decoder.paths == [thermal]
    assert decoder.overrides == {"emissivity": 0.95}

    result = manifest["capture_groups"][0]
    temperature_path = output / result["temperature_tif"]
    preview_path = output / result["preview_png"]
    metadata_path = output / result["thermal_json"]

    temperature_data = tifffile.imread(temperature_path)
    assert temperature_data.dtype == np.float32
    assert temperature_data.shape == (2, 3)
    assert temperature_data[1, 1] == np.float32(42.5)

    with Image.open(preview_path) as preview:
        assert preview.mode == "L"
        assert preview.size == (3, 2)

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["radiometry"]["unit"] == "degree_Celsius"
    assert metadata["radiometry"]["statistics"]["max_c"] == 42.5
    assert metadata["radiometry"]["measurement_abi"] == "AMBIENT_V2"
    assert metadata["radiometry"]["api_version"] == {"api": 8, "magic": "DIRP"}
    assert manifest["capture_groups"][0]["api_version"] == {"api": 8, "magic": "DIRP"}
    assert metadata["registration"]["wide_thermal_coregistered"] is False
    assert metadata["registration"]["georeferenced_temperature_raster"] is False
    assert (output / "result-manifest.json").is_file()


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

    with pytest.raises(ValueError, match="SHA256 mismatch"):
        process_handoff(handoff_path, tmp_path / "out", FakeDecoder())
