from __future__ import annotations

from pathlib import Path

import pytest

from thermal_worker.dji_sdk import DjiThermalSdk, ThermalSdkError


def test_measurement_override_validation_accepts_values_for_sdk_range_check():
    values = DjiThermalSdk._validate_overrides(
        {
            "distance_m": 250,
            "humidity_pct": 65,
            "emissivity": 0.95,
            "reflection_c": 20,
            "ambient_temp_c": 22,
        }
    )
    assert values == {
        "distance_m": 250.0,
        "humidity_pct": 65.0,
        "emissivity": 0.95,
        "reflection_c": 20.0,
        "ambient_temp_c": 22.0,
    }


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("distance_m", 0),
        ("humidity_pct", -1),
        ("humidity_pct", 101),
        ("emissivity", 0),
        ("emissivity", 1.1),
        ("reflection_c", float("nan")),
    ],
)
def test_measurement_override_basic_validation_fails_closed(key, value):
    with pytest.raises(ValueError):
        DjiThermalSdk._validate_overrides({key: value})


def test_sdk_specific_measurement_range_is_authoritative():
    DjiThermalSdk._validate_against_sdk_ranges(
        {"distance_m": 250.0, "emissivity": 0.95},
        {
            "distance_m": {"min": 1.0, "max": 500.0},
            "emissivity": {"min": 0.1, "max": 1.0},
        },
    )
    with pytest.raises(ValueError, match="outside DJI DIRP range"):
        DjiThermalSdk._validate_against_sdk_ranges(
            {"distance_m": 600.0},
            {"distance_m": {"min": 1.0, "max": 500.0}},
        )


def test_unknown_measurement_override_is_rejected():
    with pytest.raises(ValueError, match="Unsupported measurement overrides"):
        DjiThermalSdk._validate_overrides({"fake_parameter": 1.0})


def test_thermal_sdk_error_preserves_dirp_code():
    error = ThermalSdkError("dirp_measure_ex", -7)
    assert error.operation == "dirp_measure_ex"
    assert error.code == -7
    assert "RJPEG_PARSE" in str(error)



def _fake_sdk(*, measure_code=0):
    import ctypes

    import thermal_worker.dji_sdk as dji

    sdk = object.__new__(DjiThermalSdk)
    sdk._measurement_abi = "AMBIENT_V2"
    sdk._api_version_abi = "HANDLE_V2"
    sdk.sdk_label = "fake-tsdk"
    sdk._library_path = Path("libdirp.so")
    sdk._library_sha256 = "b" * 64
    destroyed = []

    def create(_raw, _size, handle_ptr):
        ctypes.cast(
            handle_ptr,
            ctypes.POINTER(ctypes.c_void_p),
        ).contents.value = 0x1234
        return 0

    def get_api_version(_handle, version_ptr):
        version = ctypes.cast(
            version_ptr,
            ctypes.POINTER(dji._DirpApiVersion),
        ).contents
        version.api = 8
        version.magic = b"DIRP"
        return 0

    def get_rjpeg_version(_handle, version_ptr):
        version = ctypes.cast(
            version_ptr,
            ctypes.POINTER(dji._DirpRjpegVersion),
        ).contents
        version.rjpeg = 3
        version.header = 4
        version.curve = 5
        return 0

    def get_resolution(_handle, resolution_ptr):
        resolution = ctypes.cast(
            resolution_ptr,
            ctypes.POINTER(dji._DirpResolution),
        ).contents
        resolution.width = 3
        resolution.height = 2
        return 0

    def get_measurement_range(_handle, range_ptr):
        value = ctypes.cast(
            range_ptr,
            ctypes.POINTER(dji._DirpMeasurementParamsRangeV2),
        ).contents
        value.distance.min = 1.0
        value.distance.max = 500.0
        value.humidity.min = 0.0
        value.humidity.max = 100.0
        value.emissivity.min = 0.1
        value.emissivity.max = 1.0
        value.reflection.min = -40.0
        value.reflection.max = 500.0
        value.ambient_temp.min = -40.0
        value.ambient_temp.max = 500.0
        return 0

    def get_measurement(_handle, _params_ptr):
        return dji.DIRP_ERROR_UNSUPPORTED_FUNC

    def measure_ex(_handle, data_ptr, size_bytes):
        if measure_code != 0:
            return measure_code
        assert size_bytes.value == 6 * ctypes.sizeof(ctypes.c_float)
        for index, value in enumerate((10.0, 11.0, 12.0, 13.0, 14.0, 15.0)):
            data_ptr[index] = value
        return 0

    def destroy(handle):
        destroyed.append(handle.value)
        return 0

    sdk._create = create
    sdk._get_api_version = get_api_version
    sdk._get_version = get_rjpeg_version
    sdk._get_resolution = get_resolution
    sdk._get_measurement_range = get_measurement_range
    sdk._get_measurement = get_measurement
    sdk._set_measurement = lambda _handle, _params: 0
    sdk._measure_ex = measure_ex
    sdk._destroy = destroy
    return sdk, destroyed


def test_decode_uses_sdk_reported_resolution_and_versions():
    sdk, destroyed = _fake_sdk()

    result = sdk.decode_bytes(b"fake-rjpeg")

    assert result.temperature_c.shape == (2, 3)
    assert result.temperature_c.tolist() == [
        [10.0, 11.0, 12.0],
        [13.0, 14.0, 15.0],
    ]
    assert result.width == 3
    assert result.height == 2
    assert result.api_version == {"api": 8, "magic": "DIRP"}
    assert result.rjpeg_version == {"rjpeg": 3, "header": 4, "curve": 5}
    assert result.measurement_mode == "sdk_native_locked"
    assert result.measurement_error_code == -12
    assert result.sdk_library_name == "libdirp.so"
    assert result.sdk_library_sha256 == "b" * 64
    assert result.measurement_ranges["distance_m"] == {
        "min": 1.0,
        "max": 500.0,
    }
    assert destroyed == [0x1234]


def test_decode_destroys_dirp_handle_when_measurement_fails():
    sdk, destroyed = _fake_sdk(measure_code=-7)

    with pytest.raises(ThermalSdkError, match="RJPEG_PARSE"):
        sdk.decode_bytes(b"fake-rjpeg")

    assert destroyed == [0x1234]

def _abi_probe(tmp_path, header_source: str):
    sdk_root = tmp_path / "sdk"
    header = sdk_root / "tsdk-core" / "api" / "dirp_api.h"
    header.parent.mkdir(parents=True)
    header.write_text(header_source, encoding="utf-8")
    sdk = object.__new__(DjiThermalSdk)
    sdk.sdk_dir = sdk_root
    return sdk


def test_detects_handle_api_version_abi_for_modern_dji_header(tmp_path):
    sdk = _abi_probe(
        tmp_path,
        """
        typedef void *DIRP_HANDLE;
        typedef struct { unsigned int api; char magic[8]; } dirp_api_version_t;
        int dirp_get_api_version(
            DIRP_HANDLE h,
            dirp_api_version_t *version
        );
        """,
    )

    assert sdk._detect_api_version_abi() == "HANDLE_V2"


def test_detects_global_api_version_abi_for_legacy_dji_header(tmp_path):
    sdk = _abi_probe(
        tmp_path,
        """
        typedef struct { unsigned int api; char magic[8]; } dirp_api_version_t;
        int dirp_get_api_version(
            dirp_api_version_t *version
        );
        """,
    )

    assert sdk._detect_api_version_abi() == "GLOBAL_V1"


def test_api_version_abi_is_unknown_without_confirming_header(tmp_path):
    sdk = object.__new__(DjiThermalSdk)
    sdk.sdk_dir = tmp_path / "sdk-without-header"
    sdk.sdk_dir.mkdir()

    assert sdk._detect_api_version_abi() == "UNKNOWN"


def test_decode_skips_api_version_query_when_abi_is_unknown():
    sdk, destroyed = _fake_sdk()
    sdk._api_version_abi = "UNKNOWN"
    sdk._get_api_version = None

    result = sdk.decode_bytes(b"fake-rjpeg")

    assert result.api_version == {
        "api": 0,
        "magic": "UNKNOWN",
        "query_status": "SKIPPED_UNCONFIRMED_ABI",
    }
    assert destroyed == [0x1234]

def test_decode_calls_legacy_global_api_version_without_handle():
    import ctypes

    import thermal_worker.dji_sdk as dji

    sdk, destroyed = _fake_sdk()
    sdk._api_version_abi = "GLOBAL_V1"
    calls = []

    def get_api_version(version_ptr):
        calls.append("global")
        version = ctypes.cast(
            version_ptr,
            ctypes.POINTER(dji._DirpApiVersion),
        ).contents
        version.api = 4
        version.magic = b"DIRP"
        return 0

    sdk._get_api_version = get_api_version

    result = sdk.decode_bytes(b"fake-rjpeg")

    assert calls == ["global"]
    assert result.api_version == {"api": 4, "magic": "DIRP"}
    assert destroyed == [0x1234]

@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        (
            """
            float distance;
            float humidity;
            float emissivity;
            float reflection;
            """,
            "LEGACY_V1",
        ),
        (
            """
            float distance;
            float humidity;
            float emissivity;
            float reflection;
            float ambient_temp;
            """,
            "AMBIENT_V2",
        ),
    ],
)
def test_detects_measurement_abi_from_struct_fields(
    tmp_path,
    fields,
    expected,
):
    sdk = _abi_probe(
        tmp_path,
        f"""
        /* ambient_temp may be documented elsewhere in the header. */
        typedef struct {{
            {fields}
        }} dirp_measurement_params_t;
        """,
    )

    assert sdk._detect_measurement_abi() == expected


def test_conflicting_api_version_headers_fail_closed(tmp_path):
    sdk_root = tmp_path / "sdk"
    own_header = sdk_root / "tsdk-core" / "api" / "dirp_api.h"
    own_header.parent.mkdir(parents=True)
    own_header.write_text(
        """
        typedef struct { unsigned int api; char magic[8]; } dirp_api_version_t;
        int dirp_get_api_version(dirp_api_version_t *version);
        """,
        encoding="utf-8",
    )
    parent_header = tmp_path / "tsdk-core" / "api" / "dirp_api.h"
    parent_header.parent.mkdir(parents=True)
    parent_header.write_text(
        """
        typedef void *DIRP_HANDLE;
        typedef struct { unsigned int api; char magic[8]; } dirp_api_version_t;
        int dirp_get_api_version(
            DIRP_HANDLE h,
            dirp_api_version_t *version
        );
        """,
        encoding="utf-8",
    )
    sdk = object.__new__(DjiThermalSdk)
    sdk.sdk_dir = sdk_root

    assert sdk._detect_api_version_abi() == "UNKNOWN"


def test_conflicting_measurement_headers_fail_closed(tmp_path):
    sdk_root = tmp_path / "sdk"
    own_header = sdk_root / "tsdk-core" / "api" / "dirp_api.h"
    own_header.parent.mkdir(parents=True)
    own_header.write_text(
        """
        typedef struct {
            float distance;
            float humidity;
            float emissivity;
            float reflection;
        } dirp_measurement_params_t;
        """,
        encoding="utf-8",
    )
    parent_header = tmp_path / "tsdk-core" / "api" / "dirp_api.h"
    parent_header.parent.mkdir(parents=True)
    parent_header.write_text(
        """
        typedef struct {
            float distance;
            float humidity;
            float emissivity;
            float reflection;
            float ambient_temp;
        } dirp_measurement_params_t;
        """,
        encoding="utf-8",
    )
    sdk = object.__new__(DjiThermalSdk)
    sdk.sdk_dir = sdk_root

    assert sdk._detect_measurement_abi() == "UNKNOWN"


def test_multiple_sdk_releases_require_exact_release_path(
    tmp_path,
    monkeypatch,
):
    import thermal_worker.dji_sdk as dji

    monkeypatch.setattr(dji.platform, "system", lambda: "Linux")
    releases = []
    for version in ("v1", "v2"):
        release = tmp_path / version / "linux" / "release_x64"
        release.mkdir(parents=True)
        (release / "libdirp.so").write_bytes(b"placeholder")
        releases.append(release.resolve())

    with pytest.raises(
        ValueError,
        match="Multiple DJI Thermal SDK x64 releases",
    ):
        DjiThermalSdk._resolve_release_dir(tmp_path)

    assert DjiThermalSdk._resolve_release_dir(
        tmp_path / "v1"
    ) == releases[0]

def test_sdk_library_sha256_fingerprints_exact_binary(tmp_path):
    library = tmp_path / "libdirp.so"
    library.write_bytes(b"DJI-DIRP-BINARY")

    assert DjiThermalSdk._sha256_path(library) == (
        "dc49d41a85ecbb264378e70d03d00e9846e18bd84c652f2b695925cac4efca31"
    )

