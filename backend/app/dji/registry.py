from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any

from redis.asyncio import Redis

from app.config import settings
from app.dji.protocol import Envelope


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceIdentity:
    sn: str
    role: str
    domain: str | None
    type: int | None
    sub_type: int | None
    index: str | None
    thing_version: str | None
    model: str
    online: bool
    gateway_sn: str
    updated_at_ms: int


_MODEL_BY_TYPE: dict[tuple[int, int], str] = {
    (77, 0): "DJI_MAVIC_3E",
    (77, 1): "DJI_MAVIC_3T",
    (77, 2): "DJI_MAVIC_3M",
    (144, 0): "DJI_RC_PRO_ENTERPRISE",
}


def model_name(product_type: int | None, sub_type: int | None) -> str:
    if product_type is None or sub_type is None:
        return "UNKNOWN"
    return _MODEL_BY_TYPE.get((product_type, sub_type), f"DJI_TYPE_{product_type}_{sub_type}")


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _identity(
    *,
    sn: str,
    role: str,
    gateway_sn: str,
    source: dict[str, Any],
    online: bool,
    updated_at_ms: int,
) -> DeviceIdentity:
    product_type = _optional_int(source.get("type"))
    sub_type = _optional_int(source.get("sub_type"))
    domain = source.get("domain")
    return DeviceIdentity(
        sn=sn,
        role=role,
        domain=str(domain) if domain is not None else None,
        type=product_type,
        sub_type=sub_type,
        index=str(source["index"]) if source.get("index") is not None else None,
        thing_version=(
            str(source["thing_version"])
            if source.get("thing_version") is not None
            else str(source["version"])
            if source.get("version") is not None
            else None
        ),
        model=model_name(product_type, sub_type),
        online=online,
        gateway_sn=gateway_sn,
        updated_at_ms=updated_at_ms,
    )


def topology_identities(gateway_sn: str, envelope: Envelope) -> tuple[DeviceIdentity, list[DeviceIdentity]]:
    """Normalize update_topo without retaining DJI nonce/device_secret values."""

    now_ms = int(time.time() * 1000)
    data = envelope.data

    gateway = _identity(
        sn=gateway_sn,
        role="gateway",
        gateway_sn=gateway_sn,
        source=data,
        online=True,
        updated_at_ms=now_ms,
    )

    children: list[DeviceIdentity] = []
    sub_devices = data.get("sub_devices") or []
    if not isinstance(sub_devices, list):
        raise ValueError("sub_devices must be an array")

    for child in sub_devices:
        if not isinstance(child, dict):
            continue
        sn = child.get("sn")
        if not isinstance(sn, str) or not sn:
            continue
        children.append(
            _identity(
                sn=sn,
                role="aircraft",
                gateway_sn=gateway_sn,
                source=child,
                online=True,
                updated_at_ms=now_ms,
            )
        )

    return gateway, children


class DeviceRegistry:
    def __init__(self, redis: Redis):
        self.redis = redis

    @staticmethod
    def gateway_key(sn: str) -> str:
        return f"dji:gateway:{sn}"

    @staticmethod
    def device_key(sn: str) -> str:
        return f"dji:device:{sn}"

    @staticmethod
    def children_key(gateway_sn: str) -> str:
        return f"dji:gateway:{gateway_sn}:children"

    async def update_topology(self, gateway_sn: str, envelope: Envelope) -> tuple[DeviceIdentity, list[DeviceIdentity]]:
        gateway, children = topology_identities(gateway_sn, envelope)
        children_key = self.children_key(gateway_sn)

        old_children = {
            item.decode() if isinstance(item, bytes) else str(item)
            for item in await self.redis.smembers(children_key)
        }
        new_children = {child.sn for child in children}

        previous: dict[str, dict[str, Any] | None] = {}
        for sn in {gateway_sn, *old_children, *new_children}:
            raw = await self.redis.get(self.device_key(sn))
            previous[sn] = json.loads(raw) if raw else None

        offline_records: list[dict[str, Any]] = []

        pipeline = self.redis.pipeline(transaction=True)
        pipeline.set(self.gateway_key(gateway_sn), json.dumps(asdict(gateway)))
        pipeline.set(self.device_key(gateway_sn), json.dumps(asdict(gateway)))

        for child in children:
            pipeline.set(self.device_key(child.sn), json.dumps(asdict(child)))

        for offline_sn in old_children - new_children:
            record = previous.get(offline_sn)
            if record:
                record = dict(record)
                record["online"] = False
                record["updated_at_ms"] = int(time.time() * 1000)
                offline_records.append(record)
                pipeline.set(self.device_key(offline_sn), json.dumps(record))

        pipeline.delete(children_key)
        if new_children:
            pipeline.sadd(children_key, *sorted(new_children))

        await pipeline.execute()

        await self._publish_transition_if_needed(
            previous.get(gateway_sn),
            asdict(gateway),
        )
        for child in children:
            await self._publish_transition_if_needed(
                previous.get(child.sn),
                asdict(child),
            )
        for record in offline_records:
            await self._publish_live(
                {
                    "type": "device_offline",
                    "timestamp": record["updated_at_ms"],
                    "device": record,
                }
            )

        await self._publish_live(
            {
                "type": "topology",
                "timestamp": gateway.updated_at_ms,
                "gateway_sn": gateway_sn,
                "devices": [
                    asdict(gateway),
                    *[asdict(child) for child in children],
                ],
            }
        )
        return gateway, children

    async def _publish_transition_if_needed(
        self,
        previous: dict[str, Any] | None,
        current: dict[str, Any],
    ) -> None:
        if previous is not None and previous.get("online") is True:
            return
        await self._publish_live(
            {
                "type": "device_online",
                "timestamp": current["updated_at_ms"],
                "device": current,
            }
        )

    async def _publish_live(self, event: dict[str, Any]) -> None:
        try:
            await self.redis.publish(
                settings.live_redis_channel,
                json.dumps(event),
            )
        except Exception:
            # Live UI fan-out must never prevent DJI topology acknowledgement.
            logger.warning("Failed to publish live topology event", exc_info=True)

    async def get_device(self, sn: str) -> dict[str, Any] | None:
        raw = await self.redis.get(self.device_key(sn))
        return json.loads(raw) if raw else None

    async def list_devices(self) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        async for key in self.redis.scan_iter(match="dji:device:*"):
            raw = await self.redis.get(key)
            if raw:
                devices.append(json.loads(raw))
        devices.sort(key=lambda item: (item.get("role", ""), item.get("sn", "")))
        return devices
