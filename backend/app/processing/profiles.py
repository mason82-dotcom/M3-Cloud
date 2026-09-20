from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WebODMProfile:
    key: str
    title: str
    purpose: str
    options: tuple[tuple[str, Any], ...]

    def as_options(self) -> list[dict[str, Any]]:
        return [{"name": name, "value": value} for name, value in self.options]


M3E_ORTHO = WebODMProfile(
    key="m3e-ortho",
    title="M3E RTK Orthophoto / Vermessung",
    purpose="High quality orthophoto, DSM/DTM and georeferenced point cloud.",
    options=(
        ("feature-quality", "high"),
        ("pc-quality", "high"),
        ("orthophoto-resolution", 2.0),
        ("dem-resolution", 2.0),
        ("dsm", True),
        ("dtm", True),
        ("pc-classify", True),
        ("pc-las", True),
        ("pc-copc", True),
        ("build-overviews", True),
        ("auto-boundary", True),
        ("skip-3dmodel", True),
    ),
)

M3E_3D_BUILDING = WebODMProfile(
    key="m3e-3d-building",
    title="M3E 3D Gebäude",
    purpose="Dense point cloud and detailed textured mesh from nadir and oblique RGB images.",
    options=(
        ("feature-quality", "high"),
        ("min-num-features", 20000),
        ("pc-quality", "high"),
        ("mesh-size", 600000),
        ("mesh-octree-depth", 11),
        ("auto-boundary", True),
        ("sky-removal", True),
        ("gltf", True),
        ("3d-tiles", True),
        ("pc-las", True),
        ("pc-copc", True),
        ("orthophoto-resolution", 2.5),
    ),
)

M3E_FAST_CHECK = WebODMProfile(
    key="m3e-fast-check",
    title="Schneller Kontrolllauf",
    purpose="Fast coverage and image-matching check with a coarse orthophoto.",
    options=(
        ("feature-quality", "medium"),
        ("fast-orthophoto", True),
        ("orthophoto-resolution", 5.0),
        ("auto-boundary", True),
        ("matcher-neighbors", 8),
        ("skip-report", True),
        ("optimize-disk-space", True),
    ),
)

PROFILES = {
    profile.key: profile
    for profile in (M3E_ORTHO, M3E_3D_BUILDING, M3E_FAST_CHECK)
}
DEFAULT_PROFILE = M3E_ORTHO.key


def get_profile(name: str) -> WebODMProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown WebODM profile: {name}") from exc


def profile_catalog() -> list[dict[str, Any]]:
    return [
        {
            "key": profile.key,
            "title": profile.title,
            "purpose": profile.purpose,
            "options": profile.as_options(),
        }
        for profile in PROFILES.values()
    ]
