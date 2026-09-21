import asyncio
import json

import pytest

from app.dji.protocol import parse_envelope
from app.dji.services import DJIServiceClient
from app.dji.topics import TopicKind
from app.dji.transactions import DJITransactionManager


class FakePublisher:
    def __init__(self) -> None:
        self.messages = []

    async def publish(self, topic, payload, *, qos=0, retain=False):
        self.messages.append((topic, payload, qos, retain))


@pytest.mark.asyncio
async def test_service_client_correlates_tid_and_bid() -> None:
    publisher = FakePublisher()
    transactions = DJITransactionManager()
    client = DJIServiceClient(publisher, transactions, timeout_s=1.0)

    task = asyncio.create_task(
        client.call(
            "RC123",
            "live_start_push",
            {
                "video_id": "M3T123/67-0-0/normal-0",
                "video_quality": 2,
                "url_type": 1,
                "url": "rtmp://media/live",
            },
            bid="business-1",
        )
    )
    await asyncio.sleep(0)

    assert len(publisher.messages) == 1
    topic, raw, qos, retain = publisher.messages[0]
    assert topic == "thing/product/RC123/services"
    assert qos == 0
    assert retain is False

    request = parse_envelope(raw)
    assert request.method == "live_start_push"
    assert request.bid == "business-1"

    reply = parse_envelope(
        {
            "tid": request.tid,
            "bid": request.bid,
            "timestamp": 1000,
            "method": request.method,
            "data": {
                "result": 0,
                "output": {"status": "ok"},
            },
        }
    )
    assert transactions.resolve(
        TopicKind.SERVICES_REPLY,
        "RC123",
        request.tid,
        reply,
    )

    response = await task
    assert response.result == 0
    assert response.output == {"status": "ok"}
    assert response.tid == request.tid
    assert transactions.pending_count == 0


@pytest.mark.asyncio
async def test_transaction_manager_does_not_cross_resolve_gateways() -> None:
    transactions = DJITransactionManager()
    pending = transactions.register(
        TopicKind.SERVICES_REPLY,
        "RC-A",
        "same-tid",
    )

    wrong = parse_envelope(
        json.dumps(
            {
                "tid": "same-tid",
                "bid": "b",
                "timestamp": 1,
                "method": "live_stop_push",
                "data": {"result": 0},
            }
        )
    )
    assert not transactions.resolve(
        TopicKind.SERVICES_REPLY,
        "RC-B",
        "same-tid",
        wrong,
    )

    transactions.cancel(pending)
