from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Iterable

from app.models import MediaAsset


WEBODM_KINDS = frozenset({"RGB", "WIDE"})
M3T_PAIR = frozenset({"WIDE", "THERMAL"})
M3M_COMPLETE = frozenset(
    {"RGB", "MS_GREEN", "MS_RED", "MS_RED_EDGE", "MS_NIR"}
)


def dataset_prefix(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    parent = path.parent.as_posix()
    return "" if parent == "." else parent


def _workflow(
    *,
    key: str,
    ready: bool,
    eligible_assets: int,
    complete_groups: int = 0,
    incomplete_groups: int = 0,
    reason: str,
) -> dict[str, object]:
    return {
        "key": key,
        "ready": ready,
        "eligible_assets": eligible_assets,
        "complete_groups": complete_groups,
        "incomplete_groups": incomplete_groups,
        "reason": reason,
    }


def build_media_datasets(assets: Iterable[MediaAsset]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[MediaAsset]] = defaultdict(list)

    for asset in assets:
        if not asset.present or asset.duplicate_of is not None:
            continue
        prefix = dataset_prefix(asset.relative_path)
        if not prefix:
            continue
        grouped[(asset.platform, prefix)].append(asset)

    datasets: list[dict[str, object]] = []

    for (platform, prefix), items in grouped.items():
        counts = Counter(asset.media_kind for asset in items)
        total_bytes = sum(asset.size_bytes for asset in items)

        by_capture: dict[str, set[str]] = defaultdict(set)
        for asset in items:
            if asset.capture_group:
                by_capture[asset.capture_group].add(asset.media_kind)

        webodm_count = sum(counts[kind] for kind in WEBODM_KINDS)
        workflows: list[dict[str, object]] = [
            _workflow(
                key="WEBODM",
                ready=webodm_count >= 2,
                eligible_assets=webodm_count,
                reason=(
                    "At least two RGB/Wide originals available"
                    if webodm_count >= 2
                    else "WebODM requires at least two RGB/Wide originals"
                ),
            )
        ]

        if platform == "M3T":
            complete = sum(
                1 for kinds in by_capture.values()
                if M3T_PAIR.issubset(kinds)
            )
            partial = sum(
                1 for kinds in by_capture.values()
                if kinds & M3T_PAIR and not M3T_PAIR.issubset(kinds)
            )
            workflows.append(
                _workflow(
                    key="THERMOGRAM",
                    ready=complete > 0,
                    eligible_assets=complete * len(M3T_PAIR),
                    complete_groups=complete,
                    incomplete_groups=partial,
                    reason=(
                        f"{complete} complete Wide/Thermal capture groups"
                        if complete > 0
                        else "No complete Wide/Thermal capture group"
                    ),
                )
            )

        if platform == "M3M":
            complete = sum(
                1 for kinds in by_capture.values()
                if M3M_COMPLETE.issubset(kinds)
            )
            partial = sum(
                1 for kinds in by_capture.values()
                if kinds & M3M_COMPLETE and not M3M_COMPLETE.issubset(kinds)
            )
            workflows.append(
                _workflow(
                    key="MULTISPECTRAL",
                    ready=complete > 0,
                    eligible_assets=complete * len(M3M_COMPLETE),
                    complete_groups=complete,
                    incomplete_groups=partial,
                    reason=(
                        f"{complete} complete RGB + 4-band capture groups"
                        if complete > 0
                        else "No complete RGB + Green/Red/RedEdge/NIR capture group"
                    ),
                )
            )

        datasets.append(
            {
                "prefix": prefix,
                "platform": platform,
                "asset_count": len(items),
                "size_bytes": total_bytes,
                "media_kinds": dict(sorted(counts.items())),
                "capture_group_count": len(by_capture),
                "workflows": workflows,
            }
        )

    return sorted(
        datasets,
        key=lambda item: (str(item["platform"]), str(item["prefix"])),
    )
