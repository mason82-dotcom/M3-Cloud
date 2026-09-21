import asyncio

import pytest

from app.dji.liveview import DJILiveView
from app.dji.protocol import parse_envelope
from app.dji.services import DJIServiceClient
from app.dji.topics import TopicKind
from app.dji.transactions import DJITransactionManager


class FakePublisher:
    def __init__(self):
        self.messages = []

    async def publish(self, topic, payload, *, qos=0, retain=False):
        self.messages.append((topic, payload, qos, retain))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "method"),
    [
        ("start", "live_start_push"),
        ("stop", "live_stop_push"),
        ("set_quality", "live_set_quality"),
        ("set_lens", "live_lens_change"),
    ],
)
async def test_liveview_uses_official_service_methods(operation, method):
    publisher = FakePublisher()
    transactions = DJITransactionManager()
    live = DJILiveView(DJIServiceClient(publisher, transactions, timeout_s=1))

    if operation == "start":
        coro = live.start(
            "RC123",
            video_id="M3T/67-0-0/normal-0",
            url_type=1,
            url="rtmp://media/live",
            video_quality=3,
        )
    elif operation == "stop":
        coro = live.stop("RC123", video_id="M3T/67-0-0/normal-0")
    elif operation == "set_quality":
        coro = live.set_quality(
            "RC123",
            video_id="M3T/67-0-0/normal-0",
            video_quality=2,
        )
    else:
        coro = live.set_lens(
            "RC123",
            video_id="M3T/67-0-0/normal-0",
            video_type="thermal",
        )

    task = asyncio.create_task(coro)
    await asyncio.sleep(0)

    topic, raw, _, _ = publisher.messages[0]
    assert topic == "thing/product/RC123/services"
    request = parse_envelope(raw)
    assert request.method == method

    reply = parse_envelope(
        {
            "tid": request.tid,
            "bid": request.bid,
            "timestamp": 1,
            "method": method,
            "data": {"result": 0},
        }
    )
    transactions.resolve(TopicKind.SERVICES_REPLY, "RC123", request.tid, reply)

    result = await task
    assert result["method"] == method
    assert result["result"] == 0
