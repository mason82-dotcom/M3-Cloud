from pathlib import PurePosixPath

from app.media.classifier import (
    classify_media,
    reconcile_group_platforms,
)


def test_m3m_default_file_naming_is_grouped() -> None:
    paths = [
        PurePosixPath("M3M/flight/DJI_20221031174036_0001_D.JPG"),
        PurePosixPath("M3M/flight/DJI_20221031174036_0001_MS_G.TIF"),
        PurePosixPath("M3M/flight/DJI_20221031174036_0001_MS_R.TIF"),
        PurePosixPath("M3M/flight/DJI_20221031174036_0001_MS_RE.TIF"),
        PurePosixPath("M3M/flight/DJI_20221031174036_0001_MS_NIR.TIF"),
    ]
    items = [(path, classify_media(path)) for path in paths]
    reconciled = reconcile_group_platforms(items)

    groups = {item.capture_group for item in reconciled.values()}
    assert groups == {"M3M/flight/DJI_20221031174036_0001"}
    assert {item.platform for item in reconciled.values()} == {"M3M"}
    assert {item.media_kind for item in reconciled.values()} == {
        "RGB",
        "MS_GREEN",
        "MS_RED",
        "MS_RED_EDGE",
        "MS_NIR",
    }


def test_m3t_group_is_inferred_from_thermal_member() -> None:
    paths = [
        PurePosixPath("flight/DJI_0001_W.JPG"),
        PurePosixPath("flight/DJI_0001_T.JPG"),
        PurePosixPath("flight/DJI_0001_Z.JPG"),
    ]
    items = [(path, classify_media(path)) for path in paths]
    reconciled = reconcile_group_platforms(items)

    assert {item.platform for item in reconciled.values()} == {"M3T"}
    assert {item.media_kind for item in reconciled.values()} == {
        "WIDE",
        "THERMAL",
        "ZOOM",
    }


def test_folder_hint_keeps_m3e_wide_and_zoom_unambiguous() -> None:
    wide = classify_media(PurePosixPath("M3E/site/DJI_0002_W.JPG"))
    zoom = classify_media(PurePosixPath("M3E/site/DJI_0002_Z.JPG"))

    assert wide.platform == "M3E"
    assert zoom.platform == "M3E"



def test_dji_filename_capture_time_uses_configured_timezone() -> None:
    from app.media.matching import capture_time_from_filename

    captured = capture_time_from_filename(
        PurePosixPath("M3E/site/DJI_20260920120000_0001_W.JPG"),
        timezone_name="Europe/Berlin",
    )

    assert captured is not None
    assert captured.isoformat() == "2026-09-20T10:00:00+00:00"


def test_filename_without_dji_timestamp_has_no_capture_time() -> None:
    from app.media.matching import capture_time_from_filename

    assert capture_time_from_filename(
        PurePosixPath("M3E/site/DJI_0001_W.JPG"),
        timezone_name="UTC",
    ) is None

def test_m3t_rjpeg_r_suffix_is_thermal_and_groups_with_wide() -> None:
    paths = [
        PurePosixPath("flight/DJI_0001_W.JPG"),
        PurePosixPath("flight/DJI_0001_R.JPG"),
    ]
    items = [(path, classify_media(path)) for path in paths]
    reconciled = reconcile_group_platforms(items)

    assert {item.platform for item in reconciled.values()} == {"M3T"}
    assert {item.media_kind for item in reconciled.values()} == {
        "WIDE",
        "THERMAL",
    }
    assert {item.capture_group for item in reconciled.values()} == {
        "flight/DJI_0001"
    }


def test_m3m_red_band_is_not_confused_with_m3t_rjpeg_suffix() -> None:
    classified = classify_media(
        PurePosixPath("M3M/flight/DJI_0002_MS_R.TIF")
    )

    assert classified.platform == "M3M"
    assert classified.media_kind == "MS_RED"
    assert classified.capture_group == "M3M/flight/DJI_0002"

