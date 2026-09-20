from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.media.classifier import (
    MediaClassification,
    classify_media,
    reconcile_group_platforms,
    supported_image,
)
from app.media.datasets import build_media_datasets, dataset_prefix
from app.media.matching import capture_time_from_filename, match_flight_by_capture_window
from app.media.metadata import METADATA_VERSION, ExtractedMetadata, extract_media_metadata
from app.models import Flight, MediaAsset, MediaDatasetRecord


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportScanResult:
    root: str
    scanned: int
    added: int
    updated: int
    unchanged: int
    duplicates: int
    skipped_unstable: int
    marked_missing: int
    started_at: datetime
    finished_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "root": self.root,
            "scanned": self.scanned,
            "added": self.added,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "duplicates": self.duplicates,
            "skipped_unstable": self.skipped_unstable,
            "marked_missing": self.marked_missing,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
        }


@dataclass(frozen=True)
class Candidate:
    path: Path
    relative_path: PurePosixPath
    size_bytes: int
    mtime_ns: int
    classification: MediaClassification
    capture_time_utc: datetime | None


class MediaImporter:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        root: str,
        min_age_seconds: float = 5.0,
        filename_timezone: str = "UTC",
        auto_match_flights: bool = True,
        auto_match_margin_seconds: float = 300.0,
        auto_match_max_distance_m: float = 100.0,
        auto_match_min_gps_fraction: float = 0.8,
        auto_match_max_gps_samples: int = 64,
        auto_match_max_sample_time_delta_seconds: float = 5.0,
    ):
        self.sessions = sessions
        self.root = Path(root)
        self.min_age_seconds = max(0.0, min_age_seconds)
        self.filename_timezone = filename_timezone
        self.auto_match_flights = auto_match_flights
        self.auto_match_margin_seconds = max(0.0, auto_match_margin_seconds)
        self.auto_match_max_distance_m = max(0.0, auto_match_max_distance_m)
        self.auto_match_min_gps_fraction = max(
            0.0,
            min(1.0, auto_match_min_gps_fraction),
        )
        self.auto_match_max_gps_samples = max(1, auto_match_max_gps_samples)
        self.auto_match_max_sample_time_delta_seconds = max(
            0.0,
            auto_match_max_sample_time_delta_seconds,
        )
        self._scan_lock = asyncio.Lock()
        self.last_result: ImportScanResult | None = None
        self.last_error: str | None = None

    async def scan(self) -> ImportScanResult:
        async with self._scan_lock:
            started = datetime.now(timezone.utc)
            try:
                if not self.root.exists():
                    finished = datetime.now(timezone.utc)
                    result = ImportScanResult(
                        root=str(self.root),
                        scanned=0,
                        added=0,
                        updated=0,
                        unchanged=0,
                        duplicates=0,
                        skipped_unstable=0,
                        marked_missing=0,
                        started_at=started,
                        finished_at=finished,
                    )
                    self.last_result = result
                    self.last_error = "IMPORT_ROOT_UNAVAILABLE"
                    return result

                if not self.root.is_dir():
                    raise NotADirectoryError(self.root)

                raw, visible_paths, skipped_young = await asyncio.to_thread(
                    self._discover_candidates
                )
                classifications = reconcile_group_platforms(
                    [(item.relative_path, item.classification) for item in raw]
                )
                candidates = [
                    Candidate(
                        path=item.path,
                        relative_path=item.relative_path,
                        size_bytes=item.size_bytes,
                        mtime_ns=item.mtime_ns,
                        classification=classifications[item.relative_path],
                        capture_time_utc=item.capture_time_utc,
                    )
                    for item in raw
                ]

                counters = {
                    "added": 0,
                    "updated": 0,
                    "unchanged": 0,
                    "duplicates": 0,
                    "skipped_unstable": skipped_young,
                }

                async with self.sessions() as session:
                    for candidate in candidates:
                        outcome = await self._upsert_candidate(
                            session,
                            candidate,
                            seen_at=started,
                        )
                        counters[outcome] += 1

                    present_assets = (
                        await session.scalars(
                            select(MediaAsset).where(MediaAsset.present.is_(True))
                        )
                    ).all()
                    marked_missing = 0
                    for asset in present_assets:
                        if asset.relative_path not in visible_paths:
                            asset.present = False
                            marked_missing += 1

                    self._reconcile_present_duplicates(present_assets)
                    counters["duplicates"] = sum(
                        1
                        for asset in present_assets
                        if asset.present and asset.duplicate_of is not None
                    )
                    await self._sync_dataset_records(
                        session,
                        present_assets,
                        seen_at=started,
                    )
                    await session.commit()

                finished = datetime.now(timezone.utc)
                result = ImportScanResult(
                    root=str(self.root),
                    scanned=len(candidates),
                    added=counters["added"],
                    updated=counters["updated"],
                    unchanged=counters["unchanged"],
                    duplicates=counters["duplicates"],
                    skipped_unstable=counters["skipped_unstable"],
                    marked_missing=marked_missing,
                    started_at=started,
                    finished_at=finished,
                )
                self.last_result = result
                self.last_error = None
                return result
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Media import scan failed for %s", self.root)
                raise

    def status(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "exists": self.root.exists(),
            "readable": self.root.is_dir(),
            "min_age_seconds": self.min_age_seconds,
            "scan_running": self._scan_lock.locked(),
            "last_error": self.last_error,
            "last_scan": self.last_result.as_dict() if self.last_result else None,
        }

    def _discover_candidates(self) -> tuple[list[Candidate], set[str], int]:
        now = time.time()
        preliminary: list[Candidate] = []
        visible_paths: set[str] = set()
        skipped_young = 0

        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue

            relative = PurePosixPath(path.relative_to(self.root).as_posix())
            if not supported_image(relative):
                continue

            relative_value = relative.as_posix()
            visible_paths.add(relative_value)

            stat = path.stat()
            age = now - stat.st_mtime
            if age < self.min_age_seconds:
                skipped_young += 1
                continue

            preliminary.append(
                Candidate(
                    path=path,
                    relative_path=relative,
                    size_bytes=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                    classification=classify_media(relative),
                    capture_time_utc=capture_time_from_filename(
                        relative,
                        timezone_name=self.filename_timezone,
                    ),
                )
            )

        return preliminary, visible_paths, skipped_young

    async def _upsert_candidate(
        self,
        session: AsyncSession,
        candidate: Candidate,
        *,
        seen_at: datetime,
    ) -> str:
        relative_path = candidate.relative_path.as_posix()
        existing = await session.scalar(
            select(MediaAsset).where(MediaAsset.relative_path == relative_path)
        )

        same_file = (
            existing is not None
            and existing.size_bytes == candidate.size_bytes
            and existing.mtime_ns == candidate.mtime_ns
        )
        if same_file:
            existing.present = True
            existing.last_seen_at = seen_at
            changed = False
            if (
                existing.platform != candidate.classification.platform
                or existing.media_kind != candidate.classification.media_kind
                or existing.capture_group != candidate.classification.capture_group
            ):
                existing.platform = candidate.classification.platform
                existing.media_kind = candidate.classification.media_kind
                existing.capture_group = candidate.classification.capture_group
                changed = True

            if existing.metadata_version != METADATA_VERSION:
                metadata, stable = await self._extract_metadata(candidate)
                if not stable:
                    return "skipped_unstable"
                self._apply_metadata(existing, metadata)
                changed = True

            return "updated" if changed else "unchanged"

        digest, stable = await asyncio.to_thread(
            self._stable_sha256,
            candidate.path,
            candidate.size_bytes,
            candidate.mtime_ns,
        )
        if not stable:
            return "skipped_unstable"

        metadata, stable = await self._extract_metadata(candidate)
        if not stable:
            return "skipped_unstable"

        duplicate = await session.scalar(
            select(MediaAsset)
            .where(
                MediaAsset.sha256 == digest,
                MediaAsset.relative_path != relative_path,
                MediaAsset.duplicate_of.is_(None),
            )
            .order_by(MediaAsset.discovered_at, MediaAsset.relative_path)
            .limit(1)
        )

        if existing is None:
            existing = MediaAsset(
                relative_path=relative_path,
                filename=candidate.path.name,
                extension=candidate.path.suffix.lower(),
                size_bytes=candidate.size_bytes,
                mtime_ns=candidate.mtime_ns,
                sha256=digest,
                capture_time_utc=metadata.capture_time_utc,
                platform=candidate.classification.platform,
                media_kind=candidate.classification.media_kind,
                capture_group=candidate.classification.capture_group,
                storage_mode="EXTERNAL",
                external_root="media-import",
                present=True,
                duplicate_of=duplicate.id if duplicate else None,
                discovered_at=seen_at,
                last_seen_at=seen_at,
            )
            self._apply_metadata(existing, metadata)
            session.add(existing)
            return "duplicates" if duplicate else "added"

        existing.filename = candidate.path.name
        existing.extension = candidate.path.suffix.lower()
        existing.size_bytes = candidate.size_bytes
        existing.mtime_ns = candidate.mtime_ns
        existing.sha256 = digest
        existing.platform = candidate.classification.platform
        existing.media_kind = candidate.classification.media_kind
        existing.capture_group = candidate.classification.capture_group
        existing.storage_mode = "EXTERNAL"
        existing.external_root = "media-import"
        existing.present = True
        existing.duplicate_of = duplicate.id if duplicate else None
        existing.last_seen_at = seen_at
        self._apply_metadata(existing, metadata)
        return "duplicates" if duplicate else "updated"

    async def _extract_metadata(
        self,
        candidate: Candidate,
    ) -> tuple[ExtractedMetadata, bool]:
        metadata = await asyncio.to_thread(
            extract_media_metadata,
            candidate.path,
            default_timezone=self.filename_timezone,
            fallback_capture_time_utc=candidate.capture_time_utc,
        )
        after = candidate.path.stat()
        stable = (
            after.st_size == candidate.size_bytes
            and after.st_mtime_ns == candidate.mtime_ns
        )
        return metadata, stable

    @staticmethod
    def _apply_metadata(asset: MediaAsset, metadata: ExtractedMetadata) -> None:
        asset.capture_time_utc = metadata.capture_time_utc
        asset.capture_time_source = metadata.capture_time_source
        asset.metadata_version = METADATA_VERSION
        asset.metadata_status = metadata.metadata_status
        asset.metadata_error = metadata.metadata_error

        asset.camera_make = metadata.camera_make
        asset.camera_model = metadata.camera_model
        asset.camera_serial = metadata.camera_serial
        asset.lens_model = metadata.lens_model
        asset.image_width = metadata.image_width
        asset.image_height = metadata.image_height
        asset.orientation = metadata.orientation
        asset.exposure_time_s = metadata.exposure_time_s
        asset.f_number = metadata.f_number
        asset.iso = metadata.iso
        asset.focal_length_mm = metadata.focal_length_mm
        asset.focal_length_35mm = metadata.focal_length_35mm

        asset.gps_latitude = metadata.gps_latitude
        asset.gps_longitude = metadata.gps_longitude
        asset.gps_altitude_m = metadata.gps_altitude_m
        asset.gps_altitude_ref = metadata.gps_altitude_ref
        asset.dji_absolute_altitude_m = metadata.dji_absolute_altitude_m
        asset.dji_relative_altitude_m = metadata.dji_relative_altitude_m

        asset.flight_yaw_deg = metadata.flight_yaw_deg
        asset.flight_pitch_deg = metadata.flight_pitch_deg
        asset.flight_roll_deg = metadata.flight_roll_deg
        asset.gimbal_yaw_deg = metadata.gimbal_yaw_deg
        asset.gimbal_pitch_deg = metadata.gimbal_pitch_deg
        asset.gimbal_roll_deg = metadata.gimbal_roll_deg
        asset.metadata_json = metadata.metadata_json

    @staticmethod
    def _reconcile_present_duplicates(assets: list[MediaAsset]) -> None:
        """Keep exactly one present canonical asset per digest."""

        by_sha: dict[str, list[MediaAsset]] = {}
        for asset in assets:
            if asset.present:
                by_sha.setdefault(asset.sha256, []).append(asset)

        for members in by_sha.values():
            members.sort(
                key=lambda item: (
                    item.discovered_at,
                    item.relative_path,
                )
            )
            canonical = members[0]
            canonical.duplicate_of = None
            for duplicate in members[1:]:
                duplicate.duplicate_of = canonical.id

    async def _sync_dataset_records(
        self,
        session: AsyncSession,
        assets: list[MediaAsset],
        *,
        seen_at: datetime,
    ) -> None:
        summaries = build_media_datasets(assets)
        existing = (
            await session.scalars(select(MediaDatasetRecord))
        ).all()
        by_key = {
            (record.platform, record.prefix): record
            for record in existing
        }
        current_keys: set[tuple[str, str]] = set()

        for summary in summaries:
            platform = str(summary["platform"])
            prefix = str(summary["prefix"])
            key = (platform, prefix)
            current_keys.add(key)
            record = by_key.get(key)
            capture_started_at = summary.get("capture_started_at")
            capture_ended_at = summary.get("capture_ended_at")

            if record is None:
                record = MediaDatasetRecord(
                    platform=platform,
                    prefix=prefix,
                    present=True,
                    capture_started_at=capture_started_at,
                    capture_ended_at=capture_ended_at,
                    flight_assignment_source="AUTO",
                    flight_match_status="NO_CAPTURE_TIME",
                    flight_match_candidates=[],
                    flight_match_details={},
                    created_at=seen_at,
                    updated_at=seen_at,
                )
                session.add(record)
            else:
                record.present = True
                record.capture_started_at = capture_started_at
                record.capture_ended_at = capture_ended_at
                record.updated_at = seen_at

            if record.flight_assignment_source != "MANUAL":
                if self.auto_match_flights:
                    dataset_assets = [
                        asset
                        for asset in assets
                        if asset.present
                        and asset.duplicate_of is None
                        and asset.platform == platform
                        and dataset_prefix(asset.relative_path) == prefix
                    ]
                    gps_points = [
                        (float(asset.gps_latitude), float(asset.gps_longitude))
                        for asset in dataset_assets
                        if asset.gps_latitude is not None
                        and asset.gps_longitude is not None
                    ]
                    capture_points = [
                        (
                            asset.capture_time_utc,
                            float(asset.gps_latitude),
                            float(asset.gps_longitude),
                        )
                        for asset in dataset_assets
                        if asset.gps_latitude is not None
                        and asset.gps_longitude is not None
                    ]
                    match = await match_flight_by_capture_window(
                        session,
                        capture_started_at=capture_started_at,
                        capture_ended_at=capture_ended_at,
                        margin_seconds=self.auto_match_margin_seconds,
                        gps_points=gps_points,
                        capture_points=capture_points,
                        max_distance_m=self.auto_match_max_distance_m,
                        min_gps_fraction=self.auto_match_min_gps_fraction,
                        max_gps_samples=self.auto_match_max_gps_samples,
                        max_sample_time_delta_seconds=self.auto_match_max_sample_time_delta_seconds,
                    )
                    record.flight_assignment_source = "AUTO"
                    record.flight_match_status = match.status
                    record.flight_match_candidates = [
                        str(candidate_id) for candidate_id in match.candidate_ids
                    ]
                    record.flight_match_details = match.details
                    record.flight_id = match.flight_id
                    if record.survey_id is None and match.flight_id is not None:
                        matched_flight = await session.get(Flight, match.flight_id)
                        if (
                            matched_flight is not None
                            and matched_flight.survey_id is not None
                        ):
                            record.survey_id = matched_flight.survey_id
                else:
                    record.flight_assignment_source = "AUTO"
                    record.flight_match_status = "DISABLED"
                    record.flight_match_candidates = []
                    record.flight_match_details = {"validation": "DISABLED"}
                    record.flight_id = None

        for key, record in by_key.items():
            if key not in current_keys and record.present:
                record.present = False
                record.updated_at = seen_at

    @staticmethod
    def _stable_sha256(
        path: Path,
        expected_size: int,
        expected_mtime_ns: int,
    ) -> tuple[str, bool]:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)

        after = path.stat()
        stable = (
            after.st_size == expected_size
            and after.st_mtime_ns == expected_mtime_ns
        )
        return digest.hexdigest(), stable
