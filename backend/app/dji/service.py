from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis

from app.config import settings
from app.dji.mqtt import DJIMqttTransport
from app.dji.registry import DeviceRegistry
from app.dji.router import DJIMessageRouter
from app.dji.telemetry import TelemetryStore


@dataclass
class DJIService:
    registry: DeviceRegistry
    telemetry: TelemetryStore
    router: DJIMessageRouter
    transport: DJIMqttTransport

    @classmethod
    def create(cls, redis: Redis) -> "DJIService":
        registry = DeviceRegistry(redis)
        telemetry = TelemetryStore(redis)

        transport: DJIMqttTransport

        async def handle(topic: str, payload: bytes) -> None:
            await router.handle(topic, payload)

        transport = DJIMqttTransport(
            handle,
            client_id=settings.dji_mqtt_client_id,
            username=settings.dji_mqtt_username or None,
            password=settings.dji_mqtt_password or None,
        )
        router = DJIMessageRouter(registry, transport, telemetry)

        return cls(
            registry=registry,
            telemetry=telemetry,
            router=router,
            transport=transport,
        )
