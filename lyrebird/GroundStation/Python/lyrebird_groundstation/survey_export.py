"""Post-flight M3E survey packaging and optional WebODM upload.

Reads Lyrebird's actual on-RC survey artifacts for the current day:
  - captures.csv  (written by MappingRecorder; header defined there)
  - geo.txt       (written by OdmGeoFileRecorder; WebODM/ODM geo-reference format)

Both files are per-CALENDAR-DAY, aggregating every flight flown that day — there is no
per-mission or "latest flight" boundary in Lyrebird's on-device logging, so this tool only
ever exports "today".
"""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from lyrebird_groundstation.dji_client import DJIInterface
from lyrebird_groundstation.webodm_profiles import (
    DEFAULT_PROFILE,
    PROFILES,
    get_profile,
    merge_options,
)

# RTK solution strings MappingRecorder writes into captures.csv's rtk_solution column, taken
# verbatim from RtkTelemetryState.solution (see LyrebirdApp .../telemetry/RtkTelemetryState.kt).
# A stale reading is already folded back into "NONE" upstream (RtkTelemetryBridge), so there is
# no separate STALE bucket to track here.
_RTK_FIXED = "FIXED_POINT"
_RTK_FLOAT = "FLOAT"


@dataclass(frozen=True)
class SurveyQuality:
    total_rows: int
    fixed: int
    float_count: int
    other: int

    @property
    def fixed_ratio(self) -> float:
        return 0.0 if self.total_rows == 0 else self.fixed / self.total_rows

    @property
    def usable_ratio(self) -> float:
        return 0.0 if self.total_rows == 0 else (self.fixed + self.float_count) / self.total_rows


@dataclass(frozen=True)
class SurveyPackage:
    root: Path
    images_dir: Path
    captures_csv: Path
    geo_txt: Path
    manifest_json: Path
    images: tuple[Path, ...]
    failed_images: tuple[str, ...]
    quality: SurveyQuality


def _capture_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _wanted_images(rows: list[dict[str, str]]) -> list[str]:
    """Image filenames in first-seen order, deduplicated (repeat rows are possible if a plan
    triggers more than one export in the same day)."""
    seen: set[str] = set()
    result: list[str] = []
    for row in rows:
        name = (row.get("image_id") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def _quality_from_rows(rows: list[dict[str, str]]) -> SurveyQuality:
    fixed = sum(1 for row in rows if row.get("rtk_solution") == _RTK_FIXED)
    float_count = sum(1 for row in rows if row.get("rtk_solution") == _RTK_FLOAT)
    total = len(rows)
    return SurveyQuality(
        total_rows=total,
        fixed=fixed,
        float_count=float_count,
        other=total - fixed - float_count,
    )


def survey_quality_warnings(quality: SurveyQuality, failed_images: tuple[str, ...]) -> list[str]:
    """Human-readable warnings; quality issues never silently masquerade as hard failures."""
    warnings: list[str] = []
    if quality.total_rows and quality.fixed_ratio < 0.95:
        warnings.append(
            f"Only {quality.fixed_ratio:.1%} of {quality.total_rows} capture(s) are RTK FIXED "
            f"(float={quality.float_count}, other={quality.other})."
        )
    if failed_images:
        warnings.append(f"{len(failed_images)} survey image(s) failed to download from the aircraft.")
    return warnings


class SurveyPackageBuilder:
    """Pull today's Lyrebird survey from the RC and preserve the original M3E JPEGs."""

    def __init__(self, client: DJIInterface):
        self.client = client

    def build(self, output_root: str | Path) -> SurveyPackage:
        reports = self.client.downloadTodaySurveyReports(str(output_root))
        if reports is None:
            raise RuntimeError("RC reports no completed survey for today")

        root = Path(output_root)
        images_dir = root / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        captures_csv = Path(reports["captures"])
        geo_txt = Path(reports["geo"])

        rows = _capture_rows(captures_csv)
        wanted = _wanted_images(rows)
        if len(wanted) < 2:
            raise RuntimeError(
                f"Survey has only {len(wanted)} image(s) logged; WebODM needs at least 2"
            )
        quality = _quality_from_rows(rows)

        downloaded: list[Path] = []
        failed: list[str] = []
        for name in wanted:
            destination = images_dir / Path(name).name
            if destination.is_file() and destination.stat().st_size > 0:
                downloaded.append(destination)
                continue
            saved = self.client.downloadByName(name, save_path=str(destination))
            if saved is None:
                failed.append(name)
                continue
            downloaded.append(destination)

        # WebODM/ODM auto-detects a file literally named geo.txt in the image folder.
        (images_dir / "geo.txt").write_text(geo_txt.read_text(encoding="utf-8"), encoding="utf-8")

        manifest = {
            "schemaVersion": 1,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "source": {
                "type": "lyrebird-m3e-survey",
                "rcHost": self.client.IP_RC,
                "droneName": self.client.drone_name,
            },
            "reports": {
                "captures": captures_csv.name,
                "geo": geo_txt.name,
            },
            "quality": {
                "totalRows": quality.total_rows,
                "rtkFixed": quality.fixed,
                "rtkFloat": quality.float_count,
                "rtkOther": quality.other,
                "rtkFixedRatio": quality.fixed_ratio,
                "rtkUsableRatio": quality.usable_ratio,
            },
            "images": {
                "requested": len(wanted),
                "downloaded": len(downloaded),
                "failed": failed,
                "files": [f"images/{path.name}" for path in downloaded],
            },
        }
        manifest_path = root / "survey.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return SurveyPackage(
            root=root,
            images_dir=images_dir,
            captures_csv=captures_csv,
            geo_txt=geo_txt,
            manifest_json=manifest_path,
            images=tuple(downloaded),
            failed_images=tuple(failed),
            quality=quality,
        )


def annotate_manifest_for_webodm(
    package: SurveyPackage,
    *,
    profile_name: str,
    options: list[dict[str, Any]],
) -> None:
    """Record the actual WebODM processing recipe beside the original survey metadata."""
    manifest = json.loads(package.manifest_json.read_text(encoding="utf-8"))
    profile = get_profile(profile_name)
    manifest["webodm"] = {
        "profile": profile.key,
        "profileTitle": profile.title,
        "profilePurpose": profile.purpose,
        "options": options,
    }
    package.manifest_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


class WebODMClient:
    """Small client for WebODM's project/task API.

    Images use WebODM's partial-task workflow: create placeholder, upload one image per request,
    then commit. This keeps M3E surveys memory-bounded even with hundreds of large JPEGs.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        if token:
            self.session.headers["Authorization"] = f"JWT {token}"
        elif username and password:
            self.authenticate(username, password)

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/{path.lstrip('/')}"

    def authenticate(self, username: str, password: str) -> str:
        response = self.session.post(
            self._url("token-auth/"),
            data={"username": username, "password": password},
            timeout=30,
        )
        response.raise_for_status()
        token = response.json()["token"]
        self.session.headers["Authorization"] = f"JWT {token}"
        return token

    def create_project(self, name: str) -> int:
        response = self.session.post(
            self._url("projects/"),
            data={"name": name},
            timeout=30,
        )
        response.raise_for_status()
        return int(response.json()["id"])

    def create_partial_task(
        self,
        project_id: int,
        name: str,
        options: list[dict[str, Any]] | None = None,
    ) -> int:
        response = self.session.post(
            self._url(f"projects/{project_id}/tasks/"),
            data={
                "name": name,
                "partial": "true",
                "auto_processing_node": "true",
                "options": json.dumps(options or []),
            },
            timeout=30,
        )
        response.raise_for_status()
        return int(response.json()["id"])

    def upload_image(self, project_id: int, task_id: int, image: Path) -> None:
        mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"
        with image.open("rb") as handle:
            response = self.session.post(
                self._url(f"projects/{project_id}/tasks/{task_id}/upload/"),
                files={"images": (image.name, handle, mime)},
                timeout=180,
            )
        response.raise_for_status()

    def commit_task(self, project_id: int, task_id: int) -> dict[str, Any]:
        response = self.session.post(
            self._url(f"projects/{project_id}/tasks/{task_id}/commit/"),
            timeout=60,
        )
        response.raise_for_status()
        return dict(response.json())

    def upload_package(
        self,
        package: SurveyPackage,
        *,
        project_id: int | None = None,
        project_name: str | None = None,
        task_name: str | None = None,
        options: list[dict[str, Any]] | None = None,
    ) -> tuple[int, int, dict[str, Any]]:
        # geo.txt rides along inside images_dir but is not itself an image upload.
        images = [path for path in package.images if path.name != "geo.txt"]
        if len(images) < 2:
            raise RuntimeError("WebODM task requires at least two downloaded survey images")
        if project_id is None:
            project_id = self.create_project(project_name or package.root.name)

        task_id = self.create_partial_task(
            project_id,
            task_name or package.root.name,
            options=options,
        )
        for image in images:
            self.upload_image(project_id, task_id, image)
        # geo.txt supplies WebODM/ODM with RTK-preferred positions per the geo-reference format.
        self.upload_image(project_id, task_id, package.images_dir / "geo.txt")
        task = self.commit_task(project_id, task_id)
        return project_id, task_id, task


def _parse_option(raw: str) -> dict[str, Any]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("WebODM option must be NAME=VALUE")
    name, raw_value = raw.split("=", 1)
    name = name.strip()
    if not name:
        raise argparse.ArgumentTypeError("WebODM option name cannot be empty")
    value: Any = raw_value.strip()
    try:
        value = json.loads(value)
    except json.JSONDecodeError:
        pass
    return {"name": name, "value": value}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download today's Lyrebird M3E survey and optionally submit it to WebODM."
    )
    parser.add_argument("--rc", default=os.getenv("LYREBIRD_RC"), required=False)
    parser.add_argument("--output", default="./lyrebird-surveys")
    parser.add_argument("--webodm", default=os.getenv("WEBODM_URL"))
    parser.add_argument("--webodm-token", default=os.getenv("WEBODM_TOKEN"))
    parser.add_argument("--webodm-user", default=os.getenv("WEBODM_USERNAME"))
    parser.add_argument("--webodm-project-id", type=int)
    parser.add_argument("--webodm-project-name")
    parser.add_argument("--task-name")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default=DEFAULT_PROFILE,
        help=(
            "WebODM processing profile. "
            f"Default: {DEFAULT_PROFILE}. "
            "Use --option NAME=VALUE to override individual profile values."
        ),
    )
    parser.add_argument("--option", action="append", type=_parse_option, default=[])
    args = parser.parse_args()

    if not args.rc:
        parser.error("--rc or LYREBIRD_RC is required")

    drone = DJIInterface(args.rc, query_config_name=True)
    package = SurveyPackageBuilder(drone).build(args.output)
    print(f"Survey package: {package.root}")
    print(f"Images: {len(package.images)} downloaded, {len(package.failed_images)} failed")
    for warning in survey_quality_warnings(package.quality, package.failed_images):
        print(f"WARNING: {warning}")

    profile = get_profile(args.profile)
    odm_options = merge_options(profile, args.option)
    annotate_manifest_for_webodm(package, profile_name=profile.key, options=odm_options)
    print(f"WebODM profile: {profile.key} — {profile.title}")

    if not args.webodm:
        return

    password = os.getenv("WEBODM_PASSWORD")
    odm = WebODMClient(
        args.webodm,
        token=args.webodm_token,
        username=args.webodm_user,
        password=password,
    )
    project_id, task_id, task = odm.upload_package(
        package,
        project_id=args.webodm_project_id,
        project_name=args.webodm_project_name,
        task_name=args.task_name,
        options=odm_options,
    )
    print(f"WebODM submitted: project={project_id} task={task_id} status={task.get('status')}")


if __name__ == "__main__":
    main()
