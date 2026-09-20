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
