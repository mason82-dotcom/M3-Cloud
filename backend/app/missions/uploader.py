from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from app.config import settings
from app.missions.plans import mission_runtime_id
from app.vehicles.lyrebird import aircraft_serial, merge_identity_config


class MissionUploadError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class MissionTarget:
    host: str
    system_id: int
    executor: str


@dataclass(frozen=True)
class MissionUploadResult:
    host: str
    system_id: int
    executor: str
    item_count: int
    requested_sequences: tuple[int, ...]
    ack_result: int
    runtime_mission_id: int
    readback_verified: bool
    readback_item_count: int
    readback_runtime_mission_id: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "system_id": self.system_id,
            "executor": self.executor,
            "item_count": self.item_count,
            "requested_sequences": list(self.requested_sequences),
            "ack_result": self.ack_result,
            "runtime_mission_id": self.runtime_mission_id,
            "readback_verified": self.readback_verified,
            "readback_item_count": self.readback_item_count,
            "readback_runtime_mission_id": self.readback_runtime_mission_id,
            "execution_started": False,
        }


TargetResolver = Callable[[str, str | None], Awaitable[MissionTarget]]


class MissionUploader:
    """Upload and read back a sealed mission without ever starting execution."""

    GCS_SYSTEM = 255
    GCS_COMPONENT = 190

    @classmethod
    def _reply_for_us(cls, message: Any) -> bool:
        if message.get_type() not in (
            "MISSION_REQUEST_INT",
            "MISSION_REQUEST",
            "MISSION_ACK",
        ):
            return False
        target_system = getattr(message, "target_system", cls.GCS_SYSTEM)
        target_component = getattr(message, "target_component", cls.GCS_COMPONENT)
        return (
            int(target_system) == cls.GCS_SYSTEM
            and int(target_component) in (0, cls.GCS_COMPONENT)
        )

    @classmethod
    def _download_for_us(cls, message: Any) -> bool:
        if message.get_type() not in ("MISSION_COUNT", "MISSION_ITEM_INT"):
            return False
        target_system = getattr(message, "target_system", cls.GCS_SYSTEM)
        target_component = getattr(message, "target_component", cls.GCS_COMPONENT)
        return (
            int(target_system) == cls.GCS_SYSTEM
            and int(target_component) in (0, cls.GCS_COMPONENT)
        )

    def __init__(self, collector: Any, resolver: TargetResolver | None = None):
        self.collector = collector
        self._resolver = resolver
        self._locks: dict[str, asyncio.Lock] = {}

    async def resolve_target(
        self,
        aircraft_sn: str,
        preferred_executor: str | None,
    ) -> MissionTarget:
        if self._resolver is not None:
            return await self._resolver(aircraft_sn, preferred_executor)

        expected_executor = {
            "DJI_NATIVE": "dji_native",
            "ONBOARD": "onboard",
            None: None,
        }.get(preferred_executor)
        if preferred_executor is not None and expected_executor is None:
            raise MissionUploadError(
                "EXECUTOR_UNSUPPORTED",
                f"Unsupported mission executor {preferred_executor!r}",
            )

        hosts = [
            value.strip()
            for value in settings.lyrebird_hosts.split(",")
            if value.strip()
        ]
        if not hosts:
            raise MissionUploadError(
                "NO_LYREBIRD_HOSTS",
                "No Lyrebird hosts are configured",
            )

        async with httpx.AsyncClient() as client:
            for host in hosts:
                try:
                    config_response, settings_response = await asyncio.gather(
                        client.get(
                            f"http://{host}:{settings.lyrebird_http_port}/config",
                            timeout=settings.lyrebird_timeout_seconds,
                        ),
                        client.get(
                            f"http://{host}:{settings.lyrebird_http_port}/config/settings",
                            timeout=settings.lyrebird_timeout_seconds,
                        ),
                    )
                    if not config_response.is_success or not settings_response.is_success:
                        continue
                    config = config_response.json()
                    runtime_settings = settings_response.json()
                    if not isinstance(config, dict) or not isinstance(runtime_settings, dict):
                        continue
                    identity = merge_identity_config(config, runtime_settings)
                    if aircraft_serial(identity) != aircraft_sn:
                        continue
                except (httpx.HTTPError, ValueError):
                    continue

                route = self.collector.route_status(host)
                system_id = route.get("system_id")
                if not isinstance(system_id, int):
                    raise MissionUploadError(
                        "MAVLINK_ROUTE_UNAVAILABLE",
                        f"Lyrebird MAVLink route for {aircraft_sn} is not registered",
                        details={"host": host, "route": route},
                    )

                executor = runtime_settings.get("missionExecutor")
                if not isinstance(executor, str) or not executor:
                    raise MissionUploadError(
                        "EXECUTOR_UNVERIFIED",
                        "Lyrebird did not report its mission executor",
                        details={"host": host},
                    )
                executor = executor.strip().lower()

                if expected_executor is not None and executor != expected_executor:
                    raise MissionUploadError(
                        "EXECUTOR_MISMATCH",
                        (
                            f"Deployment expects {expected_executor!r}, "
                            f"but Lyrebird reports {executor!r}"
                        ),
                        details={
                            "host": host,
                            "expected_executor": expected_executor,
                            "actual_executor": executor,
                        },
                    )

                return MissionTarget(
                    host=host,
                    system_id=system_id,
                    executor=executor,
                )

        raise MissionUploadError(
            "AIRCRAFT_NOT_FOUND",
            f"No configured Lyrebird host reports aircraft serial {aircraft_sn!r}",
        )

    async def upload(
        self,
        package: dict[str, Any],
        *,
        aircraft_sn: str,
        preferred_executor: str | None,
    ) -> MissionUploadResult:
        handoff = package.get("handoff")
        wire = package.get("wire")
        if not isinstance(handoff, dict) or handoff.get("upload_enabled") is not True:
            raise MissionUploadError(
                "PACKAGE_NOT_UPLOADABLE",
                "This sealed deployment predates or does not permit mission upload",
            )
        if handoff.get("execution_enabled") is not False:
            raise MissionUploadError(
                "PACKAGE_EXECUTION_POLICY",
                "Deployment package does not preserve execution-disabled policy",
            )
        if not isinstance(wire, dict) or wire.get("message") != "MISSION_ITEM_INT":
            raise MissionUploadError(
                "WIRE_INVALID",
                "Deployment has no MISSION_ITEM_INT wire package",
            )

        raw_items = wire.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise MissionUploadError("WIRE_EMPTY", "Deployment contains no mission items")

        items: dict[int, dict[str, Any]] = {}
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise MissionUploadError("WIRE_INVALID", "Mission wire contains a non-object item")
            seq = raw.get("seq")
            if not isinstance(seq, int) or seq < 0 or seq in items:
                raise MissionUploadError("WIRE_SEQUENCE", "Mission wire sequence is invalid")
            items[seq] = raw

        expected_sequences = set(range(len(items)))
        if set(items) != expected_sequences:
            raise MissionUploadError(
                "WIRE_SEQUENCE",
                "Mission wire sequence must be contiguous from zero",
            )

        target = await self.resolve_target(aircraft_sn, preferred_executor)
        lock = self._locks.setdefault(target.host, asyncio.Lock())

        async with lock:
            requested: list[int] = []
            waiter = self.collector.message_waiter(
                target.host,
                self._reply_for_us,
            )
            try:
                try:
                    self.collector.send_mission_count(target.host, len(items))
                except (OSError, RuntimeError) as exc:
                    raise MissionUploadError(
                        "TRANSPORT_UNAVAILABLE",
                        "Lyrebird MAVLink transport became unavailable before upload started",
                        details={"host": target.host},
                    ) from exc

                for _ in range(len(items) * 2 + 4):
                    try:
                        reply = await asyncio.wait_for(
                            waiter,
                            timeout=settings.mission_upload_timeout_seconds,
                        )
                    except TimeoutError as exc:
                        raise MissionUploadError(
                            "UPLOAD_TIMEOUT",
                            "Timed out waiting for Lyrebird mission upload reply",
                            details={"requested_sequences": requested},
                        ) from exc

                    kind = reply.get_type()
                    if kind == "MISSION_ACK":
                        result = int(reply.type)
                        if result != 0:
                            raise MissionUploadError(
                                "MISSION_REJECTED",
                                f"Lyrebird rejected mission with MAV_MISSION_RESULT {result}",
                                details={
                                    "ack_result": result,
                                    "requested_sequences": requested,
                                },
                            )
                        readback_count, readback_id = await self._verify_readback(
                            target,
                            wire,
                        )
                        return MissionUploadResult(
                            host=target.host,
                            system_id=target.system_id,
                            executor=target.executor,
                            item_count=len(items),
                            requested_sequences=tuple(requested),
                            ack_result=result,
                            runtime_mission_id=int(wire.get("mission_id") or 0),
                            readback_verified=True,
                            readback_item_count=readback_count,
                            readback_runtime_mission_id=readback_id,
                        )

                    seq = int(reply.seq)
                    item = items.get(seq)
                    if item is None:
                        raise MissionUploadError(
                            "REQUEST_OUT_OF_RANGE",
                            f"Lyrebird requested mission item {seq}, which is not in the package",
                        )
                    requested.append(seq)

                    waiter = self.collector.message_waiter(
                        target.host,
                        self._reply_for_us,
                    )
                    try:
                        self.collector.send_mission_item_int(target.host, item)
                    except (OSError, RuntimeError) as exc:
                        raise MissionUploadError(
                            "TRANSPORT_UNAVAILABLE",
                            "Lyrebird MAVLink transport became unavailable during upload",
                            details={
                                "host": target.host,
                                "requested_sequences": requested,
                            },
                        ) from exc

                raise MissionUploadError(
                    "UPLOAD_INCOMPLETE",
                    "Mission upload did not finish within the expected handshake length",
                    details={"requested_sequences": requested},
                )
            finally:
                self.collector.remove_message_waiter(target.host, waiter)


    async def _verify_readback(
        self,
        target: MissionTarget,
        wire: dict[str, Any],
    ) -> tuple[int, int]:
        expected_items = wire.get("items")
        if not isinstance(expected_items, list):
            raise MissionUploadError(
                "READBACK_INVALID",
                "Deployment wire items are unavailable for read-back verification",
                details={"upload_acknowledged": True},
            )
        expected_count = len(expected_items)
        expected_id = int(wire.get("mission_id") or 0)

        queue = self.collector.message_queue(
            target.host,
            self._download_for_us,
        )
        try:
            try:
                self.collector.send_mission_request_list(target.host)
            except (OSError, RuntimeError) as exc:
                raise MissionUploadError(
                    "READBACK_TRANSPORT_UNAVAILABLE",
                    "Mission upload was acknowledged, but read-back could not be requested",
                    details={
                        "host": target.host,
                        "upload_acknowledged": True,
                    },
                ) from exc

            count: int | None = None
            downloaded: dict[int, dict[str, Any]] = {}
            deadline = asyncio.get_running_loop().time() + settings.mission_upload_timeout_seconds

            while count is None or len(downloaded) < count:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise MissionUploadError(
                        "READBACK_TIMEOUT",
                        "Mission upload was acknowledged, but read-back timed out",
                        details={
                            "host": target.host,
                            "upload_acknowledged": True,
                            "expected_count": expected_count,
                            "reported_count": count,
                            "received_count": len(downloaded),
                        },
                    )
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=remaining)
                except TimeoutError as exc:
                    raise MissionUploadError(
                        "READBACK_TIMEOUT",
                        "Mission upload was acknowledged, but read-back timed out",
                        details={
                            "host": target.host,
                            "upload_acknowledged": True,
                            "expected_count": expected_count,
                            "reported_count": count,
                            "received_count": len(downloaded),
                        },
                    ) from exc

                if message.get_type() == "MISSION_COUNT":
                    count = int(message.count)
                    if count != expected_count:
                        raise MissionUploadError(
                            "READBACK_COUNT_MISMATCH",
                            (
                                f"Lyrebird stored {count} mission items; "
                                f"deployment contains {expected_count}"
                            ),
                            details={
                                "upload_acknowledged": True,
                                "expected_count": expected_count,
                                "actual_count": count,
                            },
                        )
                    continue

                seq = int(message.seq)
                downloaded[seq] = {
                    "seq": seq,
                    "frame": int(message.frame),
                    "command": int(message.command),
                    "current": int(getattr(message, "current", 0)),
                    "autocontinue": int(message.autocontinue),
                    "param1": float(message.param1),
                    "param2": float(message.param2),
                    "param3": float(message.param3),
                    "param4": float(message.param4),
                    "x": int(message.x),
                    "y": int(message.y),
                    "z": float(message.z),
                    "mission_type": int(getattr(message, "mission_type", 0)),
                }

            if set(downloaded) != set(range(expected_count)):
                raise MissionUploadError(
                    "READBACK_SEQUENCE_MISMATCH",
                    "Lyrebird read-back mission sequence is incomplete",
                    details={
                        "upload_acknowledged": True,
                        "expected_sequences": list(range(expected_count)),
                        "actual_sequences": sorted(downloaded),
                    },
                )

            readback_wire = {
                "items": [downloaded[index] for index in range(expected_count)]
            }
            actual_id = mission_runtime_id(readback_wire)
            if actual_id != expected_id:
                raise MissionUploadError(
                    "READBACK_FINGERPRINT_MISMATCH",
                    (
                        f"Lyrebird read-back fingerprint {actual_id} "
                        f"does not match sealed mission {expected_id}"
                    ),
                    details={
                        "upload_acknowledged": True,
                        "expected_runtime_mission_id": expected_id,
                        "actual_runtime_mission_id": actual_id,
                    },
                )

            return expected_count, actual_id
        finally:
            self.collector.remove_message_queue(target.host, queue)
