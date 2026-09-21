from __future__ import annotations

import pytest

from thermal_worker.dji_sdk import DjiThermalSdk, ThermalSdkError


def test_measurement_override_ranges_match_modern_dirp_contract():
    values = DjiThermalSdk._validate_overrides(
        {
            "distance_m": 10,
            "humidity_pct": 65,
            "emissivity": 0.95,
            "reflection_c": 20,
            "ambient_temp_c": 22,
        }
    )
    assert values == {
        "distance_m": 10.0,
        "humidity_pct": 65.0,
        "emissivity": 0.95,
        "reflection_c": 20.0,
        "ambient_temp_c": 22.0,
    }


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("distance_m", 0.5),
        ("humidity_pct", 10),
        ("emissivity", 0.05),
        ("reflection_c", 600),
        ("ambient_temp_c", 100),
    ],
)
def test_measurement_override_ranges_fail_closed(key, value):
    with pytest.raises(ValueError):
        DjiThermalSdk._validate_overrides({key: value})


def test_unknown_measurement_override_is_rejected():
    with pytest.raises(ValueError, match="Unsupported measurement overrides"):
        DjiThermalSdk._validate_overrides({"fake_parameter": 1.0})


def test_thermal_sdk_error_preserves_dirp_code():
    error = ThermalSdkError("dirp_measure_ex", -7)
    assert error.operation == "dirp_measure_ex"
    assert error.code == -7
    assert "RJPEG_PARSE" in str(error)
