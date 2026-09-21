from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.dji.topics import TopicKind


@dataclass(frozen=True)
class TransactionKey:
    reply_kind: TopicKind
    device_sn: str
    tid: str


@dataclass(frozen=True)
class PendingTransaction:
    key: TransactionKey
    future: asyncio.Future[Any]


class DuplicateTransactionError(RuntimeError):
    pass


class DJITransactionTimeout(TimeoutError):
    def __init__(self, key: TransactionKey, timeout_s: float):
        super().__init__(
            f"DJI transaction {key.tid} for {key.device_sn} timed out after {timeout_s:.1f}s"
        )
        self.key = key
        self.timeout_s = timeout_s


class DJITransactionManager:
    """Correlate DJI Cloud API replies by reply topic, gateway/device SN and tid."""

    def __init__(self) -> None:
        self._pending: dict[TransactionKey, asyncio.Future[Any]] = {}

    def register(
        self,
        reply_kind: TopicKind,
        device_sn: str,
        tid: str,
    ) -> PendingTransaction:
        key = TransactionKey(reply_kind, device_sn, tid)
        if key in self._pending:
            raise DuplicateTransactionError(
                f"DJI transaction is already pending: {reply_kind.value}/{device_sn}/{tid}"
            )

        future = asyncio.get_running_loop().create_future()
        self._pending[key] = future
        return PendingTransaction(key, future)

    def resolve(
        self,
        reply_kind: TopicKind,
        device_sn: str,
        tid: str,
        value: Any,
    ) -> bool:
        key = TransactionKey(reply_kind, device_sn, tid)
        future = self._pending.pop(key, None)
        if future is None or future.done():
            return False
        future.set_result(value)
        return True

    def cancel(self, pending: PendingTransaction) -> None:
        future = self._pending.pop(pending.key, None)
        if future is not None and not future.done():
            future.cancel()

    async def wait(
        self,
        pending: PendingTransaction,
        *,
        timeout_s: float,
    ) -> Any:
        try:
            return await asyncio.wait_for(
                asyncio.shield(pending.future),
                timeout=max(0.1, float(timeout_s)),
            )
        except TimeoutError as exc:
            self.cancel(pending)
            raise DJITransactionTimeout(pending.key, timeout_s) from exc
        finally:
            self._pending.pop(pending.key, None)

    def cancel_all(self) -> None:
        pending = list(self._pending.values())
        self._pending.clear()
        for future in pending:
            if not future.done():
                future.cancel()

    @property
    def pending_count(self) -> int:
        return len(self._pending)
