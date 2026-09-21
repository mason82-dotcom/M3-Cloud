from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath


_SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".dng",
    ".rjpeg",
}

_M3M_BANDS = {
    "G": "MS_GREEN",
    "R": "MS_RED",
    "RE": "MS_RED_EDGE",
    "NIR": "MS_NIR",
}

_THERMAL_PLATFORMS = {"M3T", "M4T"}


@dataclass(frozen=True)
class MediaClassification:
    platform: str
    media_kind: str
    capture_group: str | None


def supported_image(path: PurePosixPath) -> bool:
    return path.suffix.lower() in _SUPPORTED_EXTENSIONS


def platform_hint(path: PurePosixPath) -> str:
    for part in path.parts[:-1]:
        value = part.upper()
        if value in {"M3E", "M3T", "M3M", "M4T"}:
            return value
    return "UNKNOWN"


def classify_media(path: PurePosixPath) -> MediaClassification:
    name = path.name
    upper = name.upper()
    hint = platform_hint(path)

    m3m = re.match(
        r"^(?P<base>.+)_MS_(?P<band>G|R|RE|NIR)\.(?:TIF|TIFF)$",
        upper,
    )
    if m3m:
        group = _group_path(path, m3m.group("base"))
        return MediaClassification(
            platform="M3M",
            media_kind=_M3M_BANDS[m3m.group("band")],
            capture_group=group,
        )

    rgb = re.match(r"^(?P<base>.+)_D\.(?:JPG|JPEG|DNG)$", upper)
    if rgb:
        return MediaClassification(
            platform=hint,
            media_kind="RGB",
            capture_group=_group_path(path, rgb.group("base")),
        )

    thermal = re.match(
        r"^(?P<base>.+)_(?:T|R)\.(?:JPG|JPEG|RJPEG)$",
        upper,
    )
    if thermal:
        # Older M3T imports without a platform directory retain the historical
        # M3T fallback. M4T imports must preserve their platform directory so
        # an R-JPEG is never silently promoted from M3T to M4T by filename.
        platform = hint if hint in _THERMAL_PLATFORMS else "M3T"
        return MediaClassification(
            platform=platform,
            media_kind="THERMAL",
            capture_group=_group_path(path, thermal.group("base")),
        )

    suffix_patterns = (
        (r"^(?P<base>.+)_W\.(?:JPG|JPEG|DNG)$", "WIDE", hint),
        (r"^(?P<base>.+)_Z\.(?:JPG|JPEG|DNG)$", "ZOOM", hint),
    )
    for pattern, kind, platform in suffix_patterns:
        match = re.match(pattern, upper)
        if match:
            return MediaClassification(
                platform=platform,
                media_kind=kind,
                capture_group=_group_path(path, match.group("base")),
            )

    generic = re.match(r"^(?P<base>DJI_.+?)\.(?:JPG|JPEG|TIF|TIFF|DNG|RJPEG)$", upper)
    return MediaClassification(
        platform=hint,
        media_kind="RGB" if path.suffix.lower() in {".jpg", ".jpeg", ".dng"} else "UNKNOWN",
        capture_group=_group_path(path, generic.group("base")) if generic else None,
    )


def _group_path(path: PurePosixPath, base: str) -> str:
    parent = path.parent.as_posix()
    return base if parent == "." else f"{parent}/{base}"


def reconcile_group_platforms(
    items: list[tuple[PurePosixPath, MediaClassification]],
) -> dict[PurePosixPath, MediaClassification]:
    """Upgrade group members when a definitive platform member identifies the capture."""

    by_group: dict[str, str] = {}
    for _, item in items:
        if item.capture_group and item.platform in {"M3M", "M3T", "M4T"}:
            current = by_group.get(item.capture_group)
            if current is None or item.platform == "M3M":
                by_group[item.capture_group] = item.platform

    result: dict[PurePosixPath, MediaClassification] = {}
    for path, item in items:
        group_platform = by_group.get(item.capture_group or "")
        platform = group_platform or item.platform
        result[path] = MediaClassification(
            platform=platform,
            media_kind=item.media_kind,
            capture_group=item.capture_group,
        )
    return result
