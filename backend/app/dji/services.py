from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from app.dji.protocol import Envelope, ProtocolError, encode_json, make_message
from app.dji.topics import TopicKind, services_topic
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
class DJIServiceResponse:
    gateway_sn: str
    method: str
    tid: str
    bid: str
    result: int
    output: dict[str, Any] | None
    envelope: Envelope


class DJIServiceResultError(RuntimeError):
    def __init__(self, response: DJIServiceResponse):
        super().__init__(
            f"DJI service {response.method!r} failed with result {response.result}"
        )
        self.response = response


class DJIServiceClient:
    """Issue Cloud -> Pilot service calls and await matching services_reply messages."""

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

    async def call(
        self,
        gateway_sn: str,
        method: str,
        data: Mapping[str, Any] | None = None,
        *,
        bid: str | None = None,
        timeout_s: float | None = None,
    ) -> DJIServiceResponse:
        tid = str(uuid.uuid4())
        business_id = bid or str(uuid.uuid4())
        pending = self.transactions.register(
            TopicKind.SERVICES_REPLY,
            gateway_sn,
            tid,
        )

        payload = make_message(
            method,
            data or {},
            tid=tid,
            bid=business_id,
        )

        try:
            await self.publisher.publish(
                services_topic(gateway_sn),
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
        if not isinstance(reply, Envelope):
            raise ProtocolError("services_reply did not contain a DJI envelope")
        if reply.method != method:
            raise ProtocolError(
                f"services_reply method mismatch: expected {method!r}, got {reply.method!r}"
            )

        result = reply.data.get("result")
        if not isinstance(result, int) or isinstance(result, bool):
            raise ProtocolError("services_reply data.result must be an integer")

        raw_output = reply.data.get("output")
        output = dict(raw_output) if isinstance(raw_output, dict) else None
        response = DJIServiceResponse(
            gateway_sn=gateway_sn,
            method=method,
            tid=reply.tid,
            bid=reply.bid,
            result=result,
            output=output,
            envelope=reply,
        )
        if result != 0:
            raise DJIServiceResultError(response)
        return response
