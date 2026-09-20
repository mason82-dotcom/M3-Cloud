from lyrebird_groundstation.webodm_profiles import (
    DEFAULT_PROFILE,
    PROFILES,
    get_profile,
    merge_options,
)


def _options(name):
    return {item["name"]: item["value"] for item in get_profile(name).as_options()}


def test_three_m3e_profiles_are_available():
    assert DEFAULT_PROFILE == "m3e-ortho"
    assert set(PROFILES) == {
        "m3e-ortho",
        "m3e-3d-building",
        "m3e-fast-check",
    }


def test_ortho_profile_prioritizes_mapping_products():
    options = _options("m3e-ortho")
    assert options["dsm"] is True
    assert options["dtm"] is True
    assert options["pc-quality"] == "high"
    assert options["orthophoto-resolution"] == 2.0
    assert options["skip-3dmodel"] is True
    assert "rolling-shutter" not in options
    assert "gps-accuracy" not in options


def test_building_profile_keeps_dense_3d_outputs():
    options = _options("m3e-3d-building")
    assert options["mesh-size"] == 600000
    assert options["mesh-octree-depth"] == 11
    assert options["pc-quality"] == "high"
    assert options["gltf"] is True
    assert options["3d-tiles"] is True
    assert options["sky-removal"] is True
    assert options.get("skip-3dmodel") is not True


def test_fast_profile_uses_sparse_fast_orthophoto_path():
    options = _options("m3e-fast-check")
    assert options["fast-orthophoto"] is True
    assert options["feature-quality"] == "medium"
    assert options["orthophoto-resolution"] == 5.0


def test_cli_options_override_profile_values_without_duplicates():
    options = merge_options(
        get_profile("m3e-ortho"),
        [
            {"name": "orthophoto-resolution", "value": 1.5},
            {"name": "dtm", "value": False},
            {"name": "tiles", "value": True},
        ],
    )
    merged = {item["name"]: item["value"] for item in options}
    assert merged["orthophoto-resolution"] == 1.5
    assert merged["dtm"] is False
    assert merged["tiles"] is True
    assert [item["name"] for item in options].count("orthophoto-resolution") == 1
