from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import mimetypes
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.media.metadata import asset_metadata_payload
from app.models import (
    MediaAsset,
    MediaDatasetRecord,
    ProcessingJob,
    ProcessingJobAsset,
    ProcessingResult,
)
from app.processing.mbtiles import publish_mbtiles
from app.processing.rastertiles import RASTER_TILE_ARCHIVES, publish_raster_tiles
from app.processing.tiles3d import THREE_D_TILE_ARCHIVES, publish_3d_tiles
from app.processing.profiles import WebODMProfile, get_profile
from app.storage import create_storage_client
from app.processing.webodm import WebODMClient


logger = logging.getLogger(__name__)

REMOTE_STATUS = {
    10: "QUEUED_REMOTE",
    20: "RUNNING",
    30: "FAILED",
    40: "IMPORTING_RESULTS",
    50: "CANCELED",
}

THERMOGRAM_KINDS = ("WIDE", "THERMAL")


def select_thermogram_assets(assets: list[MediaAsset]) -> list[MediaAsset]:
    """Freeze complete M3T Wide/Thermal capture pairs for an external Thermogram job."""

    by_group: dict[str, list[MediaAsset]] = {}
    for asset in assets:
        if (
            asset.platform != "M3T"
            or asset.media_kind not in THERMOGRAM_KINDS
            or not asset.capture_group
        ):
            continue
        by_group.setdefault(asset.capture_group, []).append(asset)

    selected: list[MediaAsset] = []
    order = {kind: index for index, kind in enumerate(THERMOGRAM_KINDS)}
    required = set(THERMOGRAM_KINDS)

    for group in sorted(by_group):
        members = by_group[group]
        by_kind = {asset.media_kind: asset for asset in members}
        if not required.issubset(by_kind):
            continue
        selected.extend(
            sorted(
                (by_kind[kind] for kind in THERMOGRAM_KINDS),
                key=lambda item: order[item.media_kind],
            )
        )

    if not selected:
        raise ValueError(
            "Thermogram requires at least one complete M3T Wide/Thermal capture pair"
        )
    return selected


def _handoff_path(root: str, prefix: str) -> str:
    base = root.strip()
    if not base:
        return prefix
    if "\\" in base and "/" not in base:
        return base.rstrip("\\/") + "\\" + prefix.replace("/", "\\")
    return base.rstrip("/\\") + "/" + prefix


def build_thermogram_handoff(
    job: ProcessingJob,
    assets: list[MediaAsset],
    *,
    handoff_root: str,
    metadata_by_id: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    if job.kind != "THERMOGRAM" or job.platform != "M3T":
        raise ValueError("Processing job is not an M3T Thermogram handoff")

    grouped: dict[str, list[MediaAsset]] = {}
    for asset in assets:
        if asset.capture_group:
            grouped.setdefault(asset.capture_group, []).append(asset)

    groups: list[dict[str, object]] = []
    for group in sorted(grouped):
        members = grouped[group]
        kinds = {asset.media_kind for asset in members}
        if not set(THERMOGRAM_KINDS).issubset(kinds):
            continue
        groups.append(
            {
                "capture_group": group,
                "files": [
                    {
                        "id": str(asset.id),
                        "relative_path": asset.relative_path,
                        "path_relative_to_input": (
                            PurePosixPath(asset.relative_path)
                            .relative_to(PurePosixPath(job.input_prefix))
                            .as_posix()
                        ),
                        "filename": asset.filename,
                        "media_kind": asset.media_kind,
                        "size_bytes": asset.size_bytes,
                        "sha256": asset.sha256,
                        "capture_time_utc": (
                            asset.capture_time_utc.isoformat()
                            if asset.capture_time_utc
                            else None
                        ),
                        "metadata": (
                            (metadata_by_id or {}).get(str(asset.id))
                            or asset_metadata_payload(asset)
                        ),
                    }
                    for asset in sorted(
                        members,
                        key=lambda item: THERMOGRAM_KINDS.index(item.media_kind),
                    )
                    if asset.media_kind in THERMOGRAM_KINDS
                ],
            }
        )

    if not groups:
        raise ValueError("Thermogram job contains no complete M3T capture pairs")

    return {
        "schema_version": 3,
        "workflow": "THERMOGRAM",
        "worker_contract": "M3T_RJPEG_V1",
        "platform": "M3T",
        "job_id": str(job.id),
        "flight_id": str(job.flight_id) if job.flight_id else None,
        "input_prefix": job.input_prefix,
        "external_path": _handoff_path(handoff_root, job.input_prefix),
        "required_media_kinds": list(THERMOGRAM_KINDS),
        "capture_group_count": len(groups),
        "asset_count": sum(len(group["files"]) for group in groups),
        "capture_groups": groups,
    }


def select_profile_assets(
    assets: list[MediaAsset],
    profile: WebODMProfile,
) -> list[MediaAsset]:
    allowed = set(profile.media_kinds)
    candidates = [asset for asset in assets if asset.media_kind in allowed]

    if not profile.require_complete_groups:
        return sorted(candidates, key=lambda item: item.relative_path)

    by_group: dict[str, list[MediaAsset]] = {}
    for asset in candidates:
        if not asset.capture_group:
            continue
        by_group.setdefault(asset.capture_group, []).append(asset)

    selected: list[MediaAsset] = []
    complete_groups = 0
    order = {kind: index for index, kind in enumerate(profile.media_kinds)}
    required = set(profile.media_kinds)

    for group in sorted(by_group):
        members = by_group[group]
        kinds = {asset.media_kind for asset in members}
        if not required.issubset(kinds):
            continue

        complete_groups += 1
        by_kind = {asset.media_kind: asset for asset in members}
        selected.extend(
            sorted(
                (by_kind[kind] for kind in profile.media_kinds),
                key=lambda item: order[item.media_kind],
            )
        )

    if complete_groups < profile.min_complete_groups:
        raise ValueError(
            f"{profile.title} requires at least "
            f"{profile.min_complete_groups} complete capture groups"
        )

    return selected


RESULT_ASSETS = frozenset(
    {
        "orthophoto.tif",
        "orthophoto.png",
        "orthophoto.mbtiles",
        "dsm.tif",
        "dtm.tif",
        "dsm_tiles.zip",
        "dtm_tiles.zip",
        "georeferenced_model.las",
        "georeferenced_model.laz",
        "georeferenced_model.ply",
        "georeferenced_model.csv",
        "textured_model.zip",
        "textured_model.glb",
        "3d_tiles_model.zip",
        "3d_tiles_pointcloud.zip",
    }
)
RESULT_BUCKET = "m3-results"


def selected_result_assets(available: list[str]) -> list[str]:
    return sorted(
        {
            item
            for item in available
            if item in RESULT_ASSETS and "/" not in item and "\\" not in item
        }
    )


def result_object_key(job_id: uuid.UUID, asset_name: str) -> str:
    return f"webodm/{job_id}/{asset_name}"


def _external_relative_path(relative_path: str) -> str:
    safe = PurePosixPath(relative_path.replace("\\", "/"))
    if safe.is_absolute() or ".." in safe.parts:
        raise ValueError("external result path must stay inside the job result folder")
    return safe.as_posix()


def external_result_object_key(job_id: uuid.UUID, relative_path: str) -> str:
    return f"external/{job_id}/{_external_relative_path(relative_path)}"


def thermal_result_manifest_details(
    root: Path,
    *,
    expected_job_id: uuid.UUID | str | None = None,
) -> dict[str, dict[str, object]]:
    manifest_path = root / "result-manifest.json"
    if not manifest_path.is_file():
        return {}

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if (
        not isinstance(manifest, dict)
        or manifest.get("contract") != "M3T_THERMAL_RESULTS_V1"
        or manifest.get("workflow") != "THERMOGRAM"
        or manifest.get("platform") != "M3T"
    ):
        return {}
    if expected_job_id is not None and manifest.get("job_id") != str(expected_job_id):
        return {}

    manifest_common: dict[str, object] = {
        "thermal_contract": "M3T_THERMAL_RESULTS_V1",
    }
    for key in ("input_fingerprint", "source_handoff_schema", "processing_options"):
        value = manifest.get(key)
        if value is not None:
            manifest_common[key] = value

    details: dict[str, dict[str, object]] = {
        "result-manifest.json": {
            **manifest_common,
            "result_kind": "THERMAL_MANIFEST",
        }
    }
    groups = manifest.get("capture_groups")
    if not isinstance(groups, list):
        return details

    field_kinds = {
        "temperature_tif": "TEMPERATURE_RASTER",
        "preview_png": "THERMAL_PREVIEW",
        "thermal_json": "THERMAL_METADATA",
        "hotspot_mask_png": "HOTSPOT_MASK",
        "hotspots_json": "HOTSPOT_ANALYSIS",
    }
    for group in groups:
        if not isinstance(group, dict):
            continue
        capture_group = group.get("capture_group")
        common: dict[str, object] = {
            **manifest_common,
            "georeferenced": False,
        }
        if isinstance(capture_group, str):
            common["capture_group"] = capture_group
        for key in (
            "width",
            "height",
            "sdk_label",
            "api_version",
            "measurement_mode",
            "measurement_abi",
            "measurement_ranges",
            "statistics",
            "hotspots",
        ):
            value = group.get(key)
            if value is not None:
                common[key] = value
        for field, result_kind in field_kinds.items():
            value = group.get(field)
            if not isinstance(value, str) or not value:
                continue
            try:
                relative = _external_relative_path(value)
            except ValueError:
                continue
            details[relative] = {
                **common,
                "result_kind": result_kind,
                "temperature_unit": (
                    "degree_Celsius"
                    if result_kind == "TEMPERATURE_RASTER"
                    else None
                ),
            }
    return details


def normalize_prefix(raw: str) -> str:
    value = raw.strip().replace("\\", "/").strip("/")
    if not value:
        raise ValueError("input_prefix cannot be empty")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("input_prefix must stay inside the media import root")
    return path.as_posix()


def resolve_asset_path(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / relative_path).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise ValueError("media asset escapes import root")
    return candidate


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def verify_frozen_input(
    path: Path,
    *,
    expected_size: int,
    expected_sha256: str,
) -> None:
    size, sha256 = _sha256_file(path)
    if size != expected_size or sha256 != expected_sha256:
        raise ValueError(
            f"Processing input changed after job creation: {path.name}"
        )


class ProcessingManager:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        media_root: str,
        media_handoff_root: str = "",
        external_result_root: str = "/processing-import",
        external_result_handoff_root: str = "",
        webodm_enabled: bool,
        webodm_url: str,
        webodm_token: str = "",
        webodm_username: str = "",
        webodm_password: str = "",
        webodm_timeout_seconds: float = 300.0,
        poll_interval_seconds: float = 5.0,
    ):
        self.sessions = sessions
        self.media_root = Path(media_root)
        self.media_handoff_root = media_handoff_root or media_root
        self.external_result_root = Path(external_result_root)
        self.external_result_handoff_root = (
            external_result_handoff_root or external_result_root
        )
        self.webodm_enabled = webodm_enabled
        self.webodm_url = webodm_url.rstrip("/")
        self.webodm_token = webodm_token
        self.webodm_username = webodm_username
        self.webodm_password = webodm_password
        self.webodm_timeout_seconds = webodm_timeout_seconds
        self.poll_interval_seconds = max(2.0, poll_interval_seconds)
        self._queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._poller: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._recover()
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._worker_loop(), name="m3-processing-worker")
        if self._poller is None or self._poller.done():
            self._poller = asyncio.create_task(self._poll_loop(), name="m3-processing-poller")

    async def stop(self) -> None:
        for task in (self._worker, self._poller):
            if task is not None:
                task.cancel()
        for task in (self._worker, self._poller):
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._worker = None
        self._poller = None

    async def create_webodm_job(
        self,
        *,
        name: str,
        input_prefix: str,
        platform: str | None,
        profile: str,
    ) -> ProcessingJob:
        if not self.webodm_enabled or not self.webodm_url:
            raise RuntimeError("WebODM integration is disabled")

        normalized_prefix = normalize_prefix(input_prefix)
        profile_value = get_profile(profile)
        platform_value = platform.upper() if platform else None

        statement = (
            select(MediaAsset)
            .where(
                MediaAsset.present.is_(True),
                MediaAsset.duplicate_of.is_(None),
                (
                    (MediaAsset.relative_path == normalized_prefix)
                    | MediaAsset.relative_path.startswith(normalized_prefix + "/")
                ),
            )
            .order_by(MediaAsset.relative_path)
        )
        if platform_value:
            statement = statement.where(MediaAsset.platform == platform_value)

        async with self.sessions() as session:
            candidates = (await session.scalars(statement)).all()

            if platform_value is None:
                candidate_platforms = {asset.platform for asset in candidates}
                if len(candidate_platforms) == 1:
                    platform_value = next(iter(candidate_platforms))

            if (
                platform_value
                and profile_value.platforms
                and platform_value not in profile_value.platforms
            ):
                raise ValueError(
                    f"Profile {profile_value.key} is not valid for {platform_value}"
                )

            assets = select_profile_assets(candidates, profile_value)
            if len(assets) < profile_value.min_assets:
                raise ValueError(
                    f"{profile_value.title} requires at least "
                    f"{profile_value.min_assets} eligible images"
                )

            dataset_statement = select(MediaDatasetRecord).where(
                MediaDatasetRecord.prefix == normalized_prefix
            )
            if platform_value:
                dataset_statement = dataset_statement.where(
                    MediaDatasetRecord.platform == platform_value
                )
            dataset_records = (
                await session.scalars(dataset_statement)
            ).all()
            dataset_record = dataset_records[0] if len(dataset_records) == 1 else None

            now = datetime.now(timezone.utc)
            job = ProcessingJob(
                kind="WEBODM",
                status="QUEUED",
                name=name.strip() or normalized_prefix.split("/")[-1],
                input_prefix=normalized_prefix,
                platform=platform_value,
                flight_id=dataset_record.flight_id if dataset_record else None,
                survey_id=dataset_record.survey_id if dataset_record else None,
                media_kinds=list(profile_value.media_kinds),
                options=profile_value.as_options(),
                image_count=len(assets),
                uploaded_count=0,
                progress=0.0,
                available_assets=[],
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            await session.flush()
            session.add_all(
                [
                    ProcessingJobAsset(
                        job_id=job.id,
                        media_asset_id=asset.id,
                        ordinal=index,
                        relative_path=asset.relative_path,
                        size_bytes=asset.size_bytes,
                        sha256=asset.sha256,
                        media_kind=asset.media_kind,
                        capture_group=asset.capture_group,
                        capture_time_utc=asset.capture_time_utc,
                        metadata_snapshot=asset_metadata_payload(asset),
                    )
                    for index, asset in enumerate(assets)
                ]
            )
            await session.commit()

        await self._queue.put(job.id)
        return job

    async def create_thermogram_job(
        self,
        *,
        name: str,
        input_prefix: str,
    ) -> ProcessingJob:
        normalized_prefix = normalize_prefix(input_prefix)

        async with self.sessions() as session:
            candidates = (
                await session.scalars(
                    select(MediaAsset)
                    .where(
                        MediaAsset.present.is_(True),
                        MediaAsset.duplicate_of.is_(None),
                        MediaAsset.platform == "M3T",
                        (
                            (MediaAsset.relative_path == normalized_prefix)
                            | MediaAsset.relative_path.startswith(normalized_prefix + "/")
                        ),
                    )
                    .order_by(MediaAsset.relative_path)
                )
            ).all()

            assets = select_thermogram_assets(candidates)

            dataset_records = (
                await session.scalars(
                    select(MediaDatasetRecord).where(
                        MediaDatasetRecord.platform == "M3T",
                        MediaDatasetRecord.prefix == normalized_prefix,
                    )
                )
            ).all()
            dataset_record = dataset_records[0] if len(dataset_records) == 1 else None

            now = datetime.now(timezone.utc)
            job = ProcessingJob(
                kind="THERMOGRAM",
                status="WAITING_EXTERNAL",
                name=name.strip() or normalized_prefix.split("/")[-1],
                input_prefix=normalized_prefix,
                platform="M3T",
                flight_id=dataset_record.flight_id if dataset_record else None,
                survey_id=dataset_record.survey_id if dataset_record else None,
                media_kinds=list(THERMOGRAM_KINDS),
                options=[
                    {"name": "workflow", "value": "THERMOGRAM_M3T"},
                    {
                        "name": "handoff_root",
                        "value": self.media_handoff_root,
                    },
                ],
                image_count=len(assets),
                uploaded_count=0,
                progress=0.0,
                available_assets=[],
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            await session.flush()
            session.add_all(
                [
                    ProcessingJobAsset(
                        job_id=job.id,
                        media_asset_id=asset.id,
                        ordinal=index,
                        relative_path=asset.relative_path,
                        size_bytes=asset.size_bytes,
                        sha256=asset.sha256,
                        media_kind=asset.media_kind,
                        capture_group=asset.capture_group,
                        capture_time_utc=asset.capture_time_utc,
                    )
                    for index, asset in enumerate(assets)
                ]
            )
            await session.commit()
            return job

    async def thermogram_handoff(self, job_id: uuid.UUID) -> dict[str, object]:
        async with self.sessions() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is None:
                raise LookupError("Processing job not found")
            if job.kind != "THERMOGRAM":
                raise ValueError("Processing job is not a Thermogram job")

            frozen = (
                await session.scalars(
                    select(ProcessingJobAsset)
                    .where(ProcessingJobAsset.job_id == job_id)
                    .order_by(ProcessingJobAsset.ordinal)
                )
            ).all()

            assets = []
            metadata_by_id: dict[str, dict[str, object]] = {}
            for item in frozen:
                source = await session.get(MediaAsset, item.media_asset_id)
                if source is None:
                    raise ValueError("Frozen media source no longer exists")
                source.relative_path = item.relative_path
                source.size_bytes = item.size_bytes
                source.sha256 = item.sha256
                source.media_kind = item.media_kind
                source.capture_group = item.capture_group
                source.capture_time_utc = item.capture_time_utc
                assets.append(source)
                metadata_by_id[str(item.media_asset_id)] = item.metadata_snapshot or {}

            handoff = build_thermogram_handoff(
                job,
                assets,
                handoff_root=self.media_handoff_root,
                metadata_by_id=metadata_by_id,
            )
            handoff["result_drop_path"] = _handoff_path(
                self.external_result_handoff_root,
                str(job.id),
            )
            return handoff

    async def claim_external_job(
        self,
        job_id: uuid.UUID,
        *,
        retry_failed: bool = False,
    ) -> ProcessingJob:
        claimable = {"WAITING_EXTERNAL"}
        if retry_failed:
            claimable.add("FAILED_EXTERNAL")

        async with self.sessions() as session:
            job = await session.scalar(
                select(ProcessingJob)
                .where(ProcessingJob.id == job_id)
                .with_for_update()
            )
            if job is None:
                raise LookupError("Processing job not found")
            if job.kind != "THERMOGRAM" or job.platform != "M3T":
                raise ValueError("External claim is only supported for M3T Thermogram jobs")
            if job.status not in claimable:
                raise RuntimeError(
                    f"Thermogram job is not claimable from {job.status}"
                )

            now = datetime.now(timezone.utc)
            job.status = "RUNNING_EXTERNAL"
            job.started_at = job.started_at or now
            job.finished_at = None
            job.progress = 0.5
            job.error = None
            job.updated_at = now
            await session.commit()
            return job

    async def update_external_job(
        self,
        job_id: uuid.UUID,
        *,
        new_status: str,
        error: str | None = None,
    ) -> ProcessingJob:
        allowed = {
            "WAITING_EXTERNAL": {"RUNNING_EXTERNAL", "COMPLETED_EXTERNAL", "FAILED_EXTERNAL"},
            "RUNNING_EXTERNAL": {"COMPLETED_EXTERNAL", "FAILED_EXTERNAL"},
            "FAILED_EXTERNAL": {"RUNNING_EXTERNAL"},
            "COMPLETED_EXTERNAL": set(),
        }
        if new_status not in {
            "RUNNING_EXTERNAL",
            "COMPLETED_EXTERNAL",
            "FAILED_EXTERNAL",
        }:
            raise ValueError("Unsupported external processing status")

        async with self.sessions() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is None:
                raise LookupError("Processing job not found")
            if job.kind != "THERMOGRAM" or job.platform != "M3T":
                raise ValueError("External status is only supported for M3T Thermogram jobs")
            # Network clients may retry after the server committed a transition but the
            # response was lost. Repeating the exact current state is therefore a no-op.
            if job.status == new_status:
                return job
            if new_status not in allowed.get(job.status, set()):
                raise ValueError(
                    f"Cannot transition Thermogram job from {job.status} to {new_status}"
                )

            now = datetime.now(timezone.utc)
            if new_status == "RUNNING_EXTERNAL":
                job.started_at = job.started_at or now
                job.finished_at = None
                job.progress = 0.5
                job.error = None
            elif new_status == "COMPLETED_EXTERNAL":
                job.started_at = job.started_at or now
                job.finished_at = now
                job.progress = 1.0
                job.error = None
            else:
                job.started_at = job.started_at or now
                job.finished_at = now
                job.error = error or "External Thermogram processing failed"

            job.status = new_status
            job.updated_at = now
            await session.commit()
            return job

    async def external_result_status(self, job_id: uuid.UUID) -> dict[str, object]:
        async with self.sessions() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is None:
                raise LookupError("Processing job not found")
            if job.kind != "THERMOGRAM" or job.platform != "M3T":
                raise ValueError("External result import is only supported for M3T Thermogram jobs")

        root = self.external_result_root / str(job_id)
        files = await asyncio.to_thread(self._external_result_files, root)
        return {
            "job_id": str(job_id),
            "drop_path": _handoff_path(
                self.external_result_handoff_root,
                str(job_id),
            ),
            "mounted": self.external_result_root.exists() and self.external_result_root.is_dir(),
            "job_folder_exists": root.exists() and root.is_dir(),
            "file_count": len(files),
            "files": [path.relative_to(root).as_posix() for path in files],
        }

    async def import_external_results(self, job_id: uuid.UUID) -> list[ProcessingResult]:
        async with self.sessions() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is None:
                raise LookupError("Processing job not found")
            if job.kind != "THERMOGRAM" or job.platform != "M3T":
                raise ValueError("External result import is only supported for M3T Thermogram jobs")
            if job.status not in {"COMPLETED_EXTERNAL", "RESULT_IMPORT_FAILED"}:
                raise ValueError(
                    "Thermogram job must be COMPLETED_EXTERNAL before importing results"
                )
            existing = {
                result.asset_name: result
                for result in (
                    await session.scalars(
                        select(ProcessingResult).where(
                            ProcessingResult.job_id == job_id
                        )
                    )
                ).all()
            }

        root = self.external_result_root / str(job_id)
        files = await asyncio.to_thread(self._external_result_files, root)
        thermal_details = await asyncio.to_thread(
            thermal_result_manifest_details,
            root,
            expected_job_id=job_id,
        )
        if not files:
            raise ValueError(
                f"No external results found in {_handoff_path(self.external_result_handoff_root, str(job_id))}"
            )

        storage = create_storage_client()
        imported: list[ProcessingResult] = []

        try:
            with tempfile.TemporaryDirectory(prefix="m3-external-results-") as temporary:
                temp_root = Path(temporary)
                for source in files:
                    relative = source.relative_to(root).as_posix()
                    if len(relative) > 255:
                        raise ValueError(
                            f"External result path is too long for the catalog: {relative}"
                        )

                    snapshot = temp_root / relative
                    snapshot.parent.mkdir(parents=True, exist_ok=True)
                    size, sha256 = await asyncio.to_thread(
                        self._snapshot_external_result,
                        source,
                        snapshot,
                    )

                    previous = existing.get(relative)
                    if previous is not None:
                        if previous.sha256 != sha256:
                            raise ValueError(
                                f"External result changed after import: {relative}"
                            )
                        imported.append(previous)
                        continue

                    content_type = (
                        mimetypes.guess_type(relative)[0]
                        or "application/octet-stream"
                    )
                    object_key = external_result_object_key(job_id, relative)
                    await asyncio.to_thread(
                        storage.upload_file,
                        str(snapshot),
                        RESULT_BUCKET,
                        object_key,
                        ExtraArgs={"ContentType": content_type},
                    )

                    result = ProcessingResult(
                        job_id=job_id,
                        asset_name=relative,
                        bucket=RESULT_BUCKET,
                        object_key=object_key,
                        size_bytes=size,
                        sha256=sha256,
                        content_type=content_type,
                        details={
                            "source": "external",
                            "workflow": "THERMOGRAM",
                            "relative_path": relative,
                            **thermal_details.get(relative, {}),
                        },
                        created_at=datetime.now(timezone.utc),
                    )
                    async with self.sessions() as session:
                        session.add(result)
                        await session.commit()
                        await session.refresh(result)
                    existing[relative] = result
                    imported.append(result)
        except Exception as exc:
            now = datetime.now(timezone.utc)
            async with self.sessions() as session:
                job = await session.get(ProcessingJob, job_id)
                if job is not None:
                    job.status = "RESULT_IMPORT_FAILED"
                    job.error = f"{type(exc).__name__}: {exc}"
                    job.updated_at = now
                    await session.commit()
            raise

        now = datetime.now(timezone.utc)
        async with self.sessions() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is not None:
                job.status = "COMPLETED"
                job.progress = 1.0
                job.available_assets = sorted(result.asset_name for result in imported)
                job.error = None
                job.updated_at = now
                job.finished_at = now
                await session.commit()

        return imported

    @staticmethod
    def _external_result_files(root: Path) -> list[Path]:
        if not root.exists():
            return []
        if not root.is_dir():
            raise NotADirectoryError(root)

        resolved_root = root.resolve()
        files: list[Path] = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(resolved_root):
                raise ValueError("External result escapes job result folder")
            files.append(path)
        return files

    @staticmethod
    def _snapshot_external_result(source: Path, destination: Path) -> tuple[int, str]:
        before = source.stat()
        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as src, destination.open("wb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        after = source.stat()
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or size != after.st_size
        ):
            raise RuntimeError(f"External result is still changing: {source.name}")
        return size, digest.hexdigest()

    async def _recover(self) -> None:
        now = datetime.now(timezone.utc)
        async with self.sessions() as session:
            await session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.status == "UPLOADING")
                .values(
                    status="INTERRUPTED",
                    error="Backend restarted during WebODM upload",
                    updated_at=now,
                    finished_at=now,
                )
            )
            # Older builds used QUEUED for both local queue state and WebODM status 10.
            # A job with remote IDs has already been uploaded and must only be polled.
            await session.execute(
                update(ProcessingJob)
                .where(
                    ProcessingJob.status == "QUEUED",
                    ProcessingJob.remote_project_id.is_not(None),
                    ProcessingJob.remote_task_id.is_not(None),
                )
                .values(
                    status="QUEUED_REMOTE",
                    updated_at=now,
                )
            )
            queued = (
                await session.scalars(
                    select(ProcessingJob.id).where(
                        ProcessingJob.status == "QUEUED",
                        ProcessingJob.remote_project_id.is_(None),
                        ProcessingJob.remote_task_id.is_(None),
                    )
                )
            ).all()
            await session.commit()

        for job_id in queued:
            await self._queue.put(job_id)

    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._run_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Processing job %s failed unexpectedly", job_id)
            finally:
                self._queue.task_done()

    async def _run_job(self, job_id: uuid.UUID) -> None:
        try:
            async with self.sessions() as session:
                job = await session.get(ProcessingJob, job_id)
                if job is None or job.status != "QUEUED":
                    return

                frozen = (
                    await session.scalars(
                        select(ProcessingJobAsset)
                        .where(ProcessingJobAsset.job_id == job_id)
                        .order_by(ProcessingJobAsset.ordinal)
                    )
                ).all()
                paths = [
                    resolve_asset_path(self.media_root, item.relative_path)
                    for item in frozen
                ]
                for path, item in zip(paths, frozen, strict=True):
                    if not path.is_file():
                        raise FileNotFoundError(path)
                    await asyncio.to_thread(
                        verify_frozen_input,
                        path,
                        expected_size=item.size_bytes,
                        expected_sha256=item.sha256,
                    )

                now = datetime.now(timezone.utc)
                job.status = "UPLOADING"
                job.started_at = now
                job.updated_at = now
                await session.commit()

                name = job.name
                options = list(job.options or [])

            client = WebODMClient(
                self.webodm_url,
                token=self.webodm_token,
                username=self.webodm_username,
                password=self.webodm_password,
                timeout_seconds=self.webodm_timeout_seconds,
            )
            try:
                project_id = await asyncio.to_thread(client.create_project, name)
                task_id = await asyncio.to_thread(
                    client.create_partial_task,
                    project_id,
                    name=name,
                    options=options,
                )
                await self._set_remote_ids(job_id, project_id, task_id)

                total = len(paths)
                for index, path in enumerate(paths, start=1):
                    await asyncio.to_thread(client.upload_image, project_id, task_id, path)
                    await self._set_upload_progress(job_id, index, total)

                task = await asyncio.to_thread(client.commit_task, project_id, task_id)
                await self._apply_remote_task(job_id, task, fallback_status="SUBMITTED")
                if task.get("status") == 40:
                    await self._import_results(job_id, task)
            finally:
                await asyncio.to_thread(client.close)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail_job(job_id, exc)

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self.poll_interval_seconds)
            try:
                await self._poll_remote_jobs()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("WebODM poll cycle failed")

    async def _poll_remote_jobs(self) -> None:
        if not self.webodm_enabled or not self.webodm_url:
            return

        async with self.sessions() as session:
            jobs = (
                await session.scalars(
                    select(ProcessingJob).where(
                        ProcessingJob.kind == "WEBODM",
                        ProcessingJob.status.in_(
                            ("SUBMITTED", "QUEUED_REMOTE", "RUNNING", "IMPORTING_RESULTS")
                        ),
                        ProcessingJob.remote_project_id.is_not(None),
                        ProcessingJob.remote_task_id.is_not(None),
                    )
                )
            ).all()

        for job in jobs:
            client = WebODMClient(
                self.webodm_url,
                token=self.webodm_token,
                username=self.webodm_username,
                password=self.webodm_password,
                timeout_seconds=self.webodm_timeout_seconds,
            )
            try:
                task = await asyncio.to_thread(
                    client.get_task,
                    int(job.remote_project_id),
                    int(job.remote_task_id),
                )
                await self._apply_remote_task(job.id, task, fallback_status=job.status)
                if task.get("status") == 40:
                    await self._import_results(job.id, task)
            except Exception as exc:
                logger.warning("Could not poll WebODM job %s: %s", job.id, exc)
            finally:
                await asyncio.to_thread(client.close)

    async def _set_remote_ids(
        self,
        job_id: uuid.UUID,
        project_id: int,
        task_id: int,
    ) -> None:
        async with self.sessions() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is None:
                return
            job.remote_project_id = project_id
            job.remote_task_id = task_id
            job.updated_at = datetime.now(timezone.utc)
            await session.commit()

    async def _set_upload_progress(
        self,
        job_id: uuid.UUID,
        uploaded: int,
        total: int,
    ) -> None:
        async with self.sessions() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is None:
                return
            job.uploaded_count = uploaded
            job.progress = 0.2 * uploaded / max(1, total)
            job.updated_at = datetime.now(timezone.utc)
            await session.commit()

    async def _apply_remote_task(
        self,
        job_id: uuid.UUID,
        task: dict[str, Any],
        *,
        fallback_status: str,
    ) -> None:
        code = task.get("status")
        remote_status = code if isinstance(code, int) else None
        status = REMOTE_STATUS.get(remote_status, fallback_status)

        running_progress = task.get("running_progress")
        upload_progress = task.get("upload_progress")
        if isinstance(running_progress, (int, float)):
            progress = 0.2 + 0.8 * max(0.0, min(1.0, float(running_progress)))
        elif isinstance(upload_progress, (int, float)):
            progress = 0.2 * max(0.0, min(1.0, float(upload_progress)))
        else:
            progress = 0.2

        if status == "IMPORTING_RESULTS":
            progress = 0.98

        now = datetime.now(timezone.utc)
        async with self.sessions() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is None:
                return
            job.remote_status = remote_status
            job.status = status
            job.progress = progress
            assets = task.get("available_assets")
            job.available_assets = [str(item) for item in assets] if isinstance(assets, list) else []
            last_error = task.get("last_error")
            if isinstance(last_error, str) and last_error:
                job.error = last_error
            if status in {"FAILED", "CANCELED"}:
                job.finished_at = now
            job.updated_at = now
            await session.commit()

    async def _import_results(
        self,
        job_id: uuid.UUID,
        task: dict[str, Any],
    ) -> None:
        available = task.get("available_assets")
        wanted = selected_result_assets(
            [str(item) for item in available] if isinstance(available, list) else []
        )

        async with self.sessions() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is None or job.remote_project_id is None or job.remote_task_id is None:
                return
            existing = set(
                (
                    await session.scalars(
                        select(ProcessingResult.asset_name).where(
                            ProcessingResult.job_id == job_id
                        )
                    )
                ).all()
            )
            project_id = int(job.remote_project_id)
            task_id = int(job.remote_task_id)

        pending = [asset for asset in wanted if asset not in existing]
        if pending:
            client = WebODMClient(
                self.webodm_url,
                token=self.webodm_token,
                username=self.webodm_username,
                password=self.webodm_password,
                timeout_seconds=self.webodm_timeout_seconds,
            )
            storage = create_storage_client()
            try:
                with tempfile.TemporaryDirectory(prefix="m3-webodm-") as temporary:
                    temp_root = Path(temporary)
                    for asset in pending:
                        destination = temp_root / asset
                        size, content_type, sha256 = await asyncio.to_thread(
                            client.download_asset,
                            project_id,
                            task_id,
                            asset,
                            destination,
                        )
                        object_key = result_object_key(job_id, asset)
                        await asyncio.to_thread(
                            storage.upload_file,
                            str(destination),
                            RESULT_BUCKET,
                            object_key,
                            ExtraArgs={"ContentType": content_type},
                        )

                        details: dict[str, object] = {}
                        if asset == "orthophoto.mbtiles":
                            details = await asyncio.to_thread(
                                publish_mbtiles,
                                storage,
                                bucket=RESULT_BUCKET,
                                job_id=job_id,
                                mbtiles_path=destination,
                            )
                        elif asset in RASTER_TILE_ARCHIVES:
                            details = await asyncio.to_thread(
                                publish_raster_tiles,
                                storage,
                                bucket=RESULT_BUCKET,
                                job_id=job_id,
                                asset_name=asset,
                                archive_path=destination,
                            )
                        elif asset in THREE_D_TILE_ARCHIVES:
                            details = await asyncio.to_thread(
                                publish_3d_tiles,
                                storage,
                                bucket=RESULT_BUCKET,
                                job_id=job_id,
                                asset_name=asset,
                                archive_path=destination,
                            )

                        async with self.sessions() as session:
                            session.add(
                                ProcessingResult(
                                    job_id=job_id,
                                    asset_name=asset,
                                    bucket=RESULT_BUCKET,
                                    object_key=object_key,
                                    size_bytes=size,
                                    sha256=sha256,
                                    content_type=content_type,
                                    details=details,
                                    created_at=datetime.now(timezone.utc),
                                )
                            )
                            await session.commit()
            except Exception as exc:
                now = datetime.now(timezone.utc)
                async with self.sessions() as session:
                    job = await session.get(ProcessingJob, job_id)
                    if job is not None:
                        job.status = "RESULT_IMPORT_FAILED"
                        job.error = f"{type(exc).__name__}: {exc}"
                        job.updated_at = now
                        job.finished_at = now
                        await session.commit()
                return
            finally:
                await asyncio.to_thread(client.close)

        now = datetime.now(timezone.utc)
        async with self.sessions() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is None:
                return
            job.status = "COMPLETED"
            job.progress = 1.0
            job.updated_at = now
            job.finished_at = now
            await session.commit()

    async def _fail_job(self, job_id: uuid.UUID, exc: Exception) -> None:
        now = datetime.now(timezone.utc)
        async with self.sessions() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is None:
                return
            job.status = "FAILED"
            job.error = f"{type(exc).__name__}: {exc}"
            job.updated_at = now
            job.finished_at = now
            await session.commit()
