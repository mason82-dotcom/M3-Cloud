from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from app.dji.protocol import (
    CorrelatedMessage,
    ProtocolError,
    encode_json,
    make_correlated_message,
)
from app.dji.topics import TopicKind, property_set_topic
from app.dji.transactions import DJITransactionManager


class Publisher(Protocol):
    async def publish(
        self,
        topic: str,
        payload: bytes,
        *,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        ...


@dataclass(frozen=True)
class DJIPropertySetResponse:
    gateway_sn: str
    tid: str
    bid: str
    results: dict[str, int]
    message: CorrelatedMessage

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(result == 0 for result in self.results.values())


class DJIPropertyClient:
    """Set writable thing-model properties and await property/set_reply."""

    def __init__(
        self,
        publisher: Publisher,
        transactions: DJITransactionManager,
        *,
        timeout_s: float = 8.0,
    ) -> None:
        self.publisher = publisher
        self.transactions = transactions
        self.timeout_s = max(0.1, float(timeout_s))

    async def set(
        self,
        gateway_sn: str,
        properties: Mapping[str, Any],
        *,
        bid: str | None = None,
        timeout_s: float | None = None,
    ) -> DJIPropertySetResponse:
        if not properties:
            raise ValueError("at least one DJI property is required")

        tid = str(uuid.uuid4())
        business_id = bid or str(uuid.uuid4())
        pending = self.transactions.register(
            TopicKind.PROPERTY_SET_REPLY,
            gateway_sn,
            tid,
        )
        payload = make_correlated_message(
            properties,
            tid=tid,
            bid=business_id,
        )

        try:
            await self.publisher.publish(
                property_set_topic(gateway_sn),
                encode_json(payload),
                qos=0,
                retain=False,
            )
        except Exception:
            self.transactions.cancel(pending)
            raise

        reply = await self.transactions.wait(
            pending,
            timeout_s=self.timeout_s if timeout_s is None else timeout_s,
        )
        if not isinstance(reply, CorrelatedMessage):
            raise ProtocolError("property/set_reply did not contain a correlated message")

        results: dict[str, int] = {}
        for name, value in reply.data.items():
            if not isinstance(value, dict):
                continue
            result = value.get("result")
            if isinstance(result, int) and not isinstance(result, bool):
                results[name] = result

        if not results:
            raise ProtocolError("property/set_reply contains no property result codes")

        return DJIPropertySetResponse(
            gateway_sn=gateway_sn,
            tid=reply.tid,
            bid=reply.bid,
            results=results,
            message=reply,
        )
