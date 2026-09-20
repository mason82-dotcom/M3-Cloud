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
from app.models import MediaAsset


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


class MediaImporter:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        root: str,
        min_age_seconds: float = 5.0,
    ):
        self.sessions = sessions
        self.root = Path(root)
        self.min_age_seconds = max(0.0, min_age_seconds)
        self._scan_lock = asyncio.Lock()
        self.last_result: ImportScanResult | None = None
        self.last_error: str | None = None

    async def scan(self) -> ImportScanResult:
        async with self._scan_lock:
            started = datetime.now(timezone.utc)
            scan_started_ns = time.time_ns()

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
            finally:
                del scan_started_ns

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

        if (
            existing is not None
            and existing.size_bytes == candidate.size_bytes
            and existing.mtime_ns == candidate.mtime_ns
        ):
            existing.present = True
            existing.last_seen_at = seen_at
            if (
                existing.platform != candidate.classification.platform
                or existing.media_kind != candidate.classification.media_kind
                or existing.capture_group != candidate.classification.capture_group
            ):
                existing.platform = candidate.classification.platform
                existing.media_kind = candidate.classification.media_kind
                existing.capture_group = candidate.classification.capture_group
                return "updated"
            return "unchanged"

        digest, stable = await asyncio.to_thread(
            self._stable_sha256,
            candidate.path,
            candidate.size_bytes,
            candidate.mtime_ns,
        )
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
        return "duplicates" if duplicate else "updated"

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
