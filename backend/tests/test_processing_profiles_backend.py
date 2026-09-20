import uuid
from datetime import datetime, timezone

import pytest

from app.models import MediaAsset
from app.processing.profiles import get_profile, profile_catalog
from app.processing.service import select_profile_assets


NOW = datetime.now(timezone.utc)


def media(kind: str, group: str | None, filename: str) -> MediaAsset:
    return MediaAsset(
        id=uuid.uuid4(),
        relative_path=f"M3M/field/{filename}",
        filename=filename,
        extension=".tif" if filename.lower().endswith(".tif") else ".jpg",
        size_bytes=100,
        mtime_ns=1,
        sha256=uuid.uuid4().hex * 2,
        platform="M3M",
        media_kind=kind,
        capture_group=group,
        storage_mode="EXTERNAL",
        external_root="media-import",
        present=True,
        duplicate_of=None,
        discovered_at=NOW,
        last_seen_at=NOW,
    )


def complete_group(index: int) -> list[MediaAsset]:
    group = f"M3M/field/DJI_{index:04d}"
    return [
        media("RGB", group, f"DJI_{index:04d}_D.JPG"),
        media("MS_GREEN", group, f"DJI_{index:04d}_MS_G.TIF"),
        media("MS_RED", group, f"DJI_{index:04d}_MS_R.TIF"),
        media("MS_RED_EDGE", group, f"DJI_{index:04d}_MS_RE.TIF"),
        media("MS_NIR", group, f"DJI_{index:04d}_MS_NIR.TIF"),
    ]


def test_m3m_profile_has_radiometric_camera_calibration() -> None:
    profile = get_profile("m3m-multispectral")
    options = {item["name"]: item["value"] for item in profile.as_options()}

    assert profile.platforms == ("M3M",)
    assert profile.workflow == "MULTISPECTRAL"
    assert options["radiometric-calibration"] == "camera"
    assert profile.require_complete_groups is True


def test_m3m_selection_keeps_only_complete_capture_groups() -> None:
    profile = get_profile("m3m-multispectral")
    assets = complete_group(1) + complete_group(2)
    assets.append(media("MS_NIR", "M3M/field/DJI_0003", "DJI_0003_MS_NIR.TIF"))

    selected = select_profile_assets(assets, profile)

    assert len(selected) == 10
    assert {asset.capture_group for asset in selected} == {
        "M3M/field/DJI_0001",
        "M3M/field/DJI_0002",
    }


def test_m3m_selection_rejects_single_complete_group() -> None:
    profile = get_profile("m3m-multispectral")

    with pytest.raises(ValueError, match="at least 2 complete capture groups"):
        select_profile_assets(complete_group(1), profile)


def test_profile_catalog_exposes_workflow_contract() -> None:
    catalog = {item["key"]: item for item in profile_catalog()}

    assert catalog["m3m-multispectral"]["workflow"] == "MULTISPECTRAL"
    assert catalog["m3m-multispectral"]["platforms"] == ["M3M"]
    assert "MS_NIR" in catalog["m3m-multispectral"]["media_kinds"]
