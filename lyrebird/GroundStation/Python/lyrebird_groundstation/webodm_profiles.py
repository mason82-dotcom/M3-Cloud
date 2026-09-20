"""WebODM processing profiles tuned for DJI Mavic 3 Enterprise RGB surveys.

The profiles intentionally do not force ``gps-accuracy``. WebODM/ODM reads high-precision RTK
metadata when present (geo.txt h_accuracy/v_accuracy columns), while a hard-coded value would
falsely claim centimetric accuracy for FLOAT/no-RTK images or datasets whose geo.txt accuracy
columns were left blank.

Likewise ``rolling-shutter`` stays disabled: the M3E wide mapping camera has a mechanical shutter.
"""

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
    purpose=(
        "Hochwertiges Orthophoto, DSM/DTM und georeferenzierte Punktwolke. "
        "3D-Mesh wird übersprungen, um Ressourcen auf Mapping-Produkte zu konzentrieren."
    ),
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
    title="M3E 3D Gebäude / Kapelle",
    purpose=(
        "Dichte Punktwolke und detaillierter texturierter Mesh für Gebäude mit Nadir- "
        "und Schrägbildern. Höhere Mesh-Dichte und GLB/3D-Tiles-Ausgabe."
    ),
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
    title="M3E schneller Kontrolllauf",
    purpose=(
        "Schnelle Feldkontrolle von Abdeckung, Bildmatching und grobem Orthophoto. "
        "Keine dichte Rekonstruktion und kein 3D-Modell."
    ),
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


PROFILES: dict[str, WebODMProfile] = {
    profile.key: profile
    for profile in (
        M3E_ORTHO,
        M3E_3D_BUILDING,
        M3E_FAST_CHECK,
    )
}

DEFAULT_PROFILE = M3E_ORTHO.key


def get_profile(name: str) -> WebODMProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        available = ", ".join(sorted(PROFILES))
        raise ValueError(f"Unknown WebODM profile {name!r}; choose one of: {available}") from exc


def merge_options(
    profile: WebODMProfile,
    overrides: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return profile options with CLI ``--option NAME=VALUE`` taking precedence."""
    merged = {entry["name"]: entry["value"] for entry in profile.as_options()}
    for entry in overrides or []:
        merged[str(entry["name"])] = entry["value"]
    return [{"name": name, "value": value} for name, value in merged.items()]


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
