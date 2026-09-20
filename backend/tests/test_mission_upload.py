import asyncio
from types import SimpleNamespace

import pytest

from app.missions.plans import mission_runtime_id
from app.missions.uploader import (
    MissionTarget,
    MissionUploadError,
    MissionUploader,
)


class FakeCollector:
    def __init__(self, item_count: int, *, ack_result: int = 0):
        self.item_count = item_count
        self.ack_result = ack_result
        self.waiters = []
        self.queues = []
        self.sent = []
        self.stored = {}

    def message_waiter(self, host, predicate):
        future = asyncio.get_running_loop().create_future()
        self.waiters.append((host, predicate, future))
        return future

    def remove_message_waiter(self, host, future):
        self.waiters = [
            item for item in self.waiters
            if item[0] != host or item[2] is not future
        ]

    def message_queue(self, host, predicate):
        queue = asyncio.Queue()
        self.queues.append((host, predicate, queue))
        return queue

    def remove_message_queue(self, host, queue):
        self.queues = [
            item for item in self.queues
            if item[0] != host or item[2] is not queue
        ]

    def _reply(self, message):
        for index, (host, predicate, future) in enumerate(list(self.waiters)):
            if not future.done() and predicate(message):
                self.waiters.pop(index)
                future.set_result(message)
                return

    def _queue(self, message):
        for _host, predicate, queue in list(self.queues):
            if predicate(message):
                queue.put_nowait(message)

    def send_mission_count(self, host, count):
        self.sent.append(("count", host, count))
        self._reply(SimpleNamespace(get_type=lambda: "MISSION_REQUEST_INT", seq=0))

    def send_mission_item_int(self, host, item):
        self.sent.append(("item", host, item["seq"]))
        self.stored[item["seq"]] = dict(item)
        next_seq = item["seq"] + 1
        if next_seq < self.item_count:
            self._reply(
                SimpleNamespace(
                    get_type=lambda: "MISSION_REQUEST_INT",
                    seq=next_seq,
                )
            )
        else:
            self._reply(
                SimpleNamespace(
                    get_type=lambda: "MISSION_ACK",
                    type=self.ack_result,
                )
            )

    def send_mission_request_list(self, host):
        self.sent.append(("request_list", host))
        self._queue(
            SimpleNamespace(
                get_type=lambda: "MISSION_COUNT",
                count=len(self.stored),
                target_system=255,
                target_component=190,
            )
        )
        for seq in sorted(self.stored):
            item = self.stored[seq]
            self._queue(
                SimpleNamespace(
                    get_type=lambda: "MISSION_ITEM_INT",
                    target_system=255,
                    target_component=190,
                    **item,
                )
            )


async def resolver(_aircraft_sn, _executor):
    return MissionTarget(
        host="10.0.0.2",
        system_id=123,
        executor="dji_native",
    )


def package(*, upload_enabled=True):
    result = {
        "handoff": {
            "upload_enabled": upload_enabled,
            "execution_enabled": False,
        },
        "wire": {
            "message": "MISSION_ITEM_INT",
            "mission_id": 0,
            "items": [
                {
                    "seq": 0,
                    "frame": 6,
                    "command": 16,
                    "current": 0,
                    "autocontinue": 1,
                    "param1": 0.0,
                    "param2": None,
                    "param3": 0.0,
                    "param4": None,
                    "x": 490000000,
                    "y": 80000000,
                    "z": 50.0,
                    "mission_type": 0,
                },
                {
                    "seq": 1,
                    "frame": 6,
                    "command": 16,
                    "current": 0,
                    "autocontinue": 1,
                    "param1": 0.0,
                    "param2": None,
                    "param3": 0.0,
                    "param4": None,
                    "x": 490001000,
                    "y": 80001000,
                    "z": 55.0,
                    "mission_type": 0,
                },
            ],
        },
    }
    result["wire"]["mission_id"] = mission_runtime_id(result["wire"])
    return result


@pytest.mark.asyncio
async def test_upload_only_completes_request_int_handshake(monkeypatch) -> None:
    monkeypatch.setattr("app.missions.uploader.settings.mission_upload_timeout_seconds", 1.0)
    collector = FakeCollector(2)
    uploader = MissionUploader(collector, resolver=resolver)

    result = await uploader.upload(
        package(),
        aircraft_sn="M3E-001",
        preferred_executor="DJI_NATIVE",
    )

    assert collector.sent == [
        ("count", "10.0.0.2", 2),
        ("item", "10.0.0.2", 0),
        ("item", "10.0.0.2", 1),
    ]
    expected_id = mission_runtime_id(package()["wire"])
    assert result.runtime_mission_id == expected_id
    assert result.readback_verified is True
    assert result.readback_runtime_mission_id == expected_id
    assert result.readback_item_count == 2
    assert result.requested_sequences == (0, 1)
    assert result.ack_result == 0
    assert result.as_dict()["execution_started"] is False
    assert collector.sent[-1] == ("request_list", "10.0.0.2")


@pytest.mark.asyncio
async def test_upload_rejects_aircraft_mission_ack(monkeypatch) -> None:
    monkeypatch.setattr("app.missions.uploader.settings.mission_upload_timeout_seconds", 1.0)
    uploader = MissionUploader(FakeCollector(2, ack_result=4), resolver=resolver)

    with pytest.raises(MissionUploadError) as exc:
        await uploader.upload(
            package(),
            aircraft_sn="M3E-001",
            preferred_executor="DJI_NATIVE",
        )
    assert exc.value.code == "MISSION_REJECTED"


@pytest.mark.asyncio
async def test_old_sealed_package_remains_non_uploadable() -> None:
    uploader = MissionUploader(FakeCollector(2), resolver=resolver)

    with pytest.raises(MissionUploadError) as exc:
        await uploader.upload(
            package(upload_enabled=False),
            aircraft_sn="M3E-001",
            preferred_executor="DJI_NATIVE",
        )
    assert exc.value.code == "PACKAGE_NOT_UPLOADABLE"



class BrokenCollector(FakeCollector):
    def send_mission_count(self, host, count):
        raise RuntimeError("socket closed")


@pytest.mark.asyncio
async def test_transport_failure_is_normalized(monkeypatch) -> None:
    monkeypatch.setattr("app.missions.uploader.settings.mission_upload_timeout_seconds", 1.0)
    uploader = MissionUploader(BrokenCollector(2), resolver=resolver)

    with pytest.raises(MissionUploadError) as exc:
        await uploader.upload(
            package(),
            aircraft_sn="M3E-001",
            preferred_executor="DJI_NATIVE",
        )

    assert exc.value.code == "TRANSPORT_UNAVAILABLE"
