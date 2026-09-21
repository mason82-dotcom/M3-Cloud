from datetime import datetime, timezone
import uuid

from app.media.datasets import build_media_datasets
from app.models import MediaAsset


NOW = datetime.now(timezone.utc)


def asset(
    path: str,
    *,
    platform: str,
    kind: str,
    group: str | None,
    size: int = 100,
    present: bool = True,
    duplicate: bool = False,
) -> MediaAsset:
    return MediaAsset(
        id=uuid.uuid4(),
        relative_path=path,
        filename=path.rsplit("/", 1)[-1],
        extension="." + path.rsplit(".", 1)[-1].lower(),
        size_bytes=size,
        mtime_ns=1,
        sha256=uuid.uuid4().hex * 2,
        platform=platform,
        media_kind=kind,
        capture_group=group,
        storage_mode="EXTERNAL",
        external_root="media-import",
        present=present,
        duplicate_of=uuid.uuid4() if duplicate else None,
        discovered_at=NOW,
        last_seen_at=NOW,
    )


def workflow(dataset: dict[str, object], key: str) -> dict[str, object]:
    values = dataset["workflows"]
    assert isinstance(values, list)
    return next(item for item in values if item["key"] == key)


def test_m3t_dataset_reports_webodm_and_thermal_readiness() -> None:
    items = [
        asset("M3T/site/DJI_0001_W.JPG", platform="M3T", kind="WIDE", group="M3T/site/DJI_0001"),
        asset("M3T/site/DJI_0001_T.JPG", platform="M3T", kind="THERMAL", group="M3T/site/DJI_0001"),
        asset("M3T/site/DJI_0002_W.JPG", platform="M3T", kind="WIDE", group="M3T/site/DJI_0002"),
        asset("M3T/site/DJI_0002_T.JPG", platform="M3T", kind="THERMAL", group="M3T/site/DJI_0002"),
    ]

    datasets = build_media_datasets(items)
    assert len(datasets) == 1
    dataset = datasets[0]

    assert dataset["prefix"] == "M3T/site"
    assert dataset["platform"] == "M3T"
    assert workflow(dataset, "WEBODM")["ready"] is True
    assert workflow(dataset, "THERMOGRAM")["ready"] is True
    assert workflow(dataset, "THERMOGRAM")["complete_groups"] == 2


def test_m4t_dataset_reports_thermal_readiness() -> None:
    items = [
        asset(
            "M4T/site/DJI_0001_R.JPG",
            platform="M4T",
            kind="THERMAL",
            group="M4T/site/DJI_0001",
        ),
        asset(
            "M4T/site/DJI_0002_W.JPG",
            platform="M4T",
            kind="WIDE",
            group="M4T/site/DJI_0002",
        ),
        asset(
            "M4T/site/DJI_0002_R.JPG",
            platform="M4T",
            kind="THERMAL",
            group="M4T/site/DJI_0002",
        ),
    ]

    dataset = build_media_datasets(items)[0]
    thermogram = workflow(dataset, "THERMOGRAM")

    assert dataset["platform"] == "M4T"
    assert thermogram["ready"] is True
    assert thermogram["complete_groups"] == 2
    assert thermogram["eligible_assets"] == 3


def test_m3t_thermal_only_group_is_thermogram_ready() -> None:
    items = [
        asset(
            "M3T/site/DJI_0001_R.JPG",
            platform="M3T",
            kind="THERMAL",
            group="M3T/site/DJI_0001",
        ),
        asset(
            "M3T/site/DJI_0002_W.JPG",
            platform="M3T",
            kind="WIDE",
            group="M3T/site/DJI_0002",
        ),
    ]

    dataset = build_media_datasets(items)[0]
    thermogram = workflow(dataset, "THERMOGRAM")

    assert thermogram["ready"] is True
    assert thermogram["complete_groups"] == 1
    assert thermogram["incomplete_groups"] == 1
    assert thermogram["eligible_assets"] == 1
    assert thermogram["reason"] == (
        "1 thermal capture groups (0 with Wide companions)"
    )


def test_m3m_dataset_requires_all_four_bands_plus_rgb() -> None:
    complete_group = "M3M/field/DJI_0001"
    partial_group = "M3M/field/DJI_0002"
    items = [
        asset("M3M/field/DJI_0001_D.JPG", platform="M3M", kind="RGB", group=complete_group),
        asset("M3M/field/DJI_0001_MS_G.TIF", platform="M3M", kind="MS_GREEN", group=complete_group),
        asset("M3M/field/DJI_0001_MS_R.TIF", platform="M3M", kind="MS_RED", group=complete_group),
        asset("M3M/field/DJI_0001_MS_RE.TIF", platform="M3M", kind="MS_RED_EDGE", group=complete_group),
        asset("M3M/field/DJI_0001_MS_NIR.TIF", platform="M3M", kind="MS_NIR", group=complete_group),
        asset("M3M/field/DJI_0002_D.JPG", platform="M3M", kind="RGB", group=partial_group),
        asset("M3M/field/DJI_0002_MS_NIR.TIF", platform="M3M", kind="MS_NIR", group=partial_group),
    ]

    dataset = build_media_datasets(items)[0]
    multi = workflow(dataset, "MULTISPECTRAL")

    assert workflow(dataset, "WEBODM")["ready"] is True
    assert multi["ready"] is False
    assert multi["complete_groups"] == 1
    assert multi["incomplete_groups"] == 1


def test_duplicates_and_missing_files_do_not_make_dataset_ready() -> None:
    items = [
        asset("M3E/site/a.JPG", platform="M3E", kind="RGB", group="M3E/site/a"),
        asset("M3E/site/b.JPG", platform="M3E", kind="RGB", group="M3E/site/b", duplicate=True),
        asset("M3E/site/c.JPG", platform="M3E", kind="RGB", group="M3E/site/c", present=False),
    ]

    dataset = build_media_datasets(items)[0]
    assert dataset["asset_count"] == 1
    assert workflow(dataset, "WEBODM")["ready"] is False


def test_thermal_manifest_keeps_original_paths_and_completeness() -> None:
    items = [
        asset("M4T/site/DJI_0001_W.JPG", platform="M4T", kind="WIDE", group="M4T/site/DJI_0001"),
        asset("M4T/site/DJI_0001_R.JPG", platform="M4T", kind="THERMAL", group="M4T/site/DJI_0001"),
        asset("M4T/site/DJI_0002_W.JPG", platform="M4T", kind="WIDE", group="M4T/site/DJI_0002"),
        asset("M4T/site/DJI_0003_R.JPG", platform="M4T", kind="THERMAL", group="M4T/site/DJI_0003"),
    ]

    from app.media.datasets import build_dataset_manifest

    manifest = build_dataset_manifest(
        items,
        prefix="M4T/site",
        import_root="/media-import",
    )

    assert manifest["schema_version"] == 2
    assert manifest["platform"] == "M4T"
    assert manifest["external_path"] == "/media-import/M4T/site"

    groups = manifest["capture_groups"]
    assert isinstance(groups, list)
    assert groups[0]["complete"] is True
    assert groups[1]["complete"] is False
    assert groups[2]["complete"] is True
    assert groups[0]["required_kinds"] == ["THERMAL"]
    assert groups[2]["required_kinds"] == ["THERMAL"]
    assert groups[0]["files"][0]["relative_path"].startswith("M4T/site/")


def test_m3m_multispectral_becomes_ready_with_two_complete_groups() -> None:
    items = []
    for index in (1, 2):
        group = f"M3M/field/DJI_{index:04d}"
        items.extend(
            [
                asset(f"{group}_D.JPG", platform="M3M", kind="RGB", group=group),
                asset(f"{group}_MS_G.TIF", platform="M3M", kind="MS_GREEN", group=group),
                asset(f"{group}_MS_R.TIF", platform="M3M", kind="MS_RED", group=group),
                asset(f"{group}_MS_RE.TIF", platform="M3M", kind="MS_RED_EDGE", group=group),
                asset(f"{group}_MS_NIR.TIF", platform="M3M", kind="MS_NIR", group=group),
            ]
        )

    dataset = build_media_datasets(items)[0]
    multi = workflow(dataset, "MULTISPECTRAL")

    assert multi["ready"] is True
    assert multi["complete_groups"] == 2
    assert multi["eligible_assets"] == 10
