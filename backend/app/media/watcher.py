from __future__ import annotations

import asyncio
import logging

from app.media.importer import MediaImporter


logger = logging.getLogger(__name__)


class MediaImportWatcher:
    def __init__(self, importer: MediaImporter, *, interval_seconds: float):
        self.importer = importer
        self.interval_seconds = max(1.0, interval_seconds)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._loop(),
                name="m3-media-import-watcher",
            )

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _loop(self) -> None:
        while True:
            try:
                await self.importer.scan()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Media import watcher scan failed")
            await asyncio.sleep(self.interval_seconds)
