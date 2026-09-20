from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import paho.mqtt.client as mqtt

from app.config import settings
from app.dji.topics import SUBSCRIPTIONS


logger = logging.getLogger(__name__)

MessageHandler = Callable[[str, bytes], Awaitable[None]]


class DJIMqttTransport:
    """MQTT v5 transport for DJI Cloud API traffic."""

    def __init__(
        self,
        handler: MessageHandler,
        *,
        host: str | None = None,
        port: int | None = None,
        client_id: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        self.handler = handler
        self.host = host or settings.emqx_host
        self.port = port or settings.emqx_port
        self._loop: asyncio.AbstractEventLoop | None = None

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id or settings.dji_mqtt_client_id,
            protocol=mqtt.MQTTv5,
        )
        if username:
            self.client.username_pw_set(username, password=password)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        await asyncio.to_thread(self.client.connect, self.host, self.port, 60)
        self.client.loop_start()

    async def stop(self) -> None:
        await asyncio.to_thread(self.client.disconnect)
        self.client.loop_stop()

    async def publish(self, topic: str, payload: bytes, *, qos: int = 0, retain: bool = False) -> None:
        info = self.client.publish(topic, payload=payload, qos=qos, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed with rc={info.rc}")
        await asyncio.to_thread(info.wait_for_publish, 5)

    def _on_connect(self, client: mqtt.Client, userdata: object, flags: object, reason_code: object, properties: object) -> None:
        del userdata, flags, properties
        if int(reason_code) != 0:
            logger.error("DJI MQTT connection rejected: %s", reason_code)
            return

        logger.info("DJI MQTT connected to %s:%s", self.host, self.port)
        for topic in SUBSCRIPTIONS:
            client.subscribe(topic, qos=0)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: object,
        disconnect_flags: object,
        reason_code: object,
        properties: object,
    ) -> None:
        del client, userdata, disconnect_flags, properties
        logger.warning("DJI MQTT disconnected: %s", reason_code)

    def _on_message(self, client: mqtt.Client, userdata: object, message: mqtt.MQTTMessage) -> None:
        del client, userdata
        if self._loop is None:
            logger.error("DJI MQTT message received before asyncio loop was registered")
            return
        future = asyncio.run_coroutine_threadsafe(
            self.handler(message.topic, bytes(message.payload)),
            self._loop,
        )
        future.add_done_callback(self._message_done)

    @staticmethod
    def _message_done(future: "asyncio.Future[None]") -> None:
        try:
            future.result()
        except Exception:
            logger.exception("Unhandled DJI MQTT message error")
