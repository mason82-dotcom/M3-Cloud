from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis

from app.config import settings
from app.dji.devices import DJIDeviceService
from app.dji.events import DJIEventDispatcher, DJIEventStateStore
from app.dji.gateway import DJIGatewayService
from app.dji.mqtt import DJIMqttTransport
from app.dji.payload_control import DJIPayloadControl
from app.dji.properties import DJIPropertyClient
from app.dji.registry import DeviceRegistry
from app.dji.requests import DJIRequestDispatcher
from app.dji.router import DJIMessageRouter
from app.dji.services import DJIServiceClient
from app.dji.telemetry import TelemetryObserver, TelemetryStore
from app.dji.transactions import DJITransactionManager


@dataclass
class DJIService:
    registry: DeviceRegistry
    telemetry: TelemetryStore
    router: DJIMessageRouter
    transport: DJIMqttTransport
    transactions: DJITransactionManager
    services: DJIServiceClient
    properties: DJIPropertyClient
    events: DJIEventDispatcher
    event_state: DJIEventStateStore
    requests: DJIRequestDispatcher
    devices: DJIDeviceService
    gateways: DJIGatewayService
    payloads: DJIPayloadControl

    @classmethod
    def create(
        cls,
        redis: Redis,
        telemetry_observer: TelemetryObserver | None = None,
    ) -> "DJIService":
        registry = DeviceRegistry(redis)
        telemetry = TelemetryStore(redis, observer=telemetry_observer)
        transactions = DJITransactionManager()
        events = DJIEventDispatcher()
        event_state = DJIEventStateStore(redis)
        event_state.register(events)
        requests = DJIRequestDispatcher()

        transport: DJIMqttTransport
        router: DJIMessageRouter

        async def handle(topic: str, payload: bytes) -> None:
            await router.handle(topic, payload)

        transport = DJIMqttTransport(
            handle,
            client_id=settings.dji_mqtt_client_id,
            username=settings.dji_mqtt_username or None,
            password=settings.dji_mqtt_password or None,
        )
        router = DJIMessageRouter(
            registry,
            transport,
            telemetry,
            transactions=transactions,
            events=events,
            event_state=event_state,
            requests=requests,
            devices=devices,
            gateways=gateways,
            payloads=payloads,
        )
        services = DJIServiceClient(transport, transactions)
        properties = DJIPropertyClient(transport, transactions)
        payloads = DJIPayloadControl(services)
        devices = DJIDeviceService(registry, telemetry, properties)
        gateways = DJIGatewayService(registry, telemetry)

        return cls(
            registry=registry,
            telemetry=telemetry,
            router=router,
            transport=transport,
            transactions=transactions,
            services=services,
            properties=properties,
            events=events,
            requests=requests,
        )
