from __future__ import annotations

import asyncio
import contextlib
import logging
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    MediaAsset,
    ProcessingJob,
    ProcessingJobAsset,
    ProcessingResult,
)
from app.processing.profiles import get_profile
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

WEBODM_MEDIA_KINDS = frozenset({"RGB", "WIDE"})

RESULT_ASSETS = frozenset(
    {
        "orthophoto.tif",
        "orthophoto.png",
        "orthophoto.mbtiles",
        "dsm.tif",
        "dtm.tif",
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


class ProcessingManager:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        media_root: str,
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
                MediaAsset.media_kind.in_(WEBODM_MEDIA_KINDS),
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
            assets = (await session.scalars(statement)).all()
            if len(assets) < 2:
                raise ValueError("WebODM requires at least two eligible RGB/Wide images")

            now = datetime.now(timezone.utc)
            job = ProcessingJob(
                kind="WEBODM",
                status="QUEUED",
                name=name.strip() or normalized_prefix.split("/")[-1],
                input_prefix=normalized_prefix,
                platform=platform_value,
                media_kinds=sorted(WEBODM_MEDIA_KINDS),
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
                    )
                    for index, asset in enumerate(assets)
                ]
            )
            await session.commit()

        await self._queue.put(job.id)
        return job

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

                rows = (
                    await session.execute(
                        select(MediaAsset)
                        .join(
                            ProcessingJobAsset,
                            ProcessingJobAsset.media_asset_id == MediaAsset.id,
                        )
                        .where(ProcessingJobAsset.job_id == job_id)
                        .order_by(ProcessingJobAsset.ordinal)
                    )
                ).scalars().all()
                paths = [
                    resolve_asset_path(self.media_root, asset.relative_path)
                    for asset in rows
                ]
                for path in paths:
                    if not path.is_file():
                        raise FileNotFoundError(path)

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
