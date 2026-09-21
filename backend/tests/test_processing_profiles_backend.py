import uuid
from datetime import datetime, timezone

import pytest

from app.models import MediaAsset
from app.processing.profiles import get_profile, profile_catalog
from app.processing.service import select_dronedb_assets


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


def test_m3m_multispectral_is_not_a_webodm_profile() -> None:
    catalog = {item["key"]: item for item in profile_catalog()}

    assert "m3m-multispectral" not in catalog
    with pytest.raises(ValueError, match="Unknown WebODM profile"):
        get_profile("m3m-multispectral")


def test_m3m_dronedb_selection_keeps_only_complete_capture_groups() -> None:
    assets = complete_group(1) + complete_group(2)
    assets.append(
        media("MS_NIR", "M3M/field/DJI_0003", "DJI_0003_MS_NIR.TIF")
    )

    selected = select_dronedb_assets(assets)

    assert len(selected) == 10
    assert {asset.capture_group for asset in selected} == {
        "M3M/field/DJI_0001",
        "M3M/field/DJI_0002",
    }


def test_m3m_dronedb_selection_rejects_single_complete_group() -> None:
    with pytest.raises(ValueError, match="at least two complete M3M"):
        select_dronedb_assets(complete_group(1))


def test_m3m_dronedb_selection_ignores_non_m3m_and_incomplete_groups() -> None:
    assets = complete_group(1) + complete_group(2)
    assets.append(
        media("MS_RED", "M3M/field/DJI_0003", "DJI_0003_MS_R.TIF")
    )
    foreign = media("RGB", "M3M/field/DJI_0004", "DJI_0004_D.JPG")
    foreign.platform = "M3E"
    assets.append(foreign)

    selected = select_dronedb_assets(assets)

    assert len(selected) == 10
    assert all(asset.platform == "M3M" for asset in selected)
