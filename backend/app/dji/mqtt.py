from __future__ import annotations

import asyncio
import logging
import threading
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
        self._connected = threading.Event()
        self._last_connection_reason: str | None = None

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

    @property
    def connected(self) -> bool:
        """Whether the DJI MQTT session has received a successful CONNACK."""

        return self._connected.is_set()

    @property
    def last_connection_reason(self) -> str | None:
        return self._last_connection_reason

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._connected.clear()
        self._last_connection_reason = None
        await asyncio.to_thread(self.client.connect, self.host, self.port, 60)
        self.client.loop_start()

    async def stop(self) -> None:
        try:
            await asyncio.to_thread(self.client.disconnect)
        finally:
            self.client.loop_stop()
            self._connected.clear()

    async def publish(
        self,
        topic: str,
        payload: bytes,
        *,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        if not self.connected:
            raise RuntimeError("DJI MQTT publish attempted while transport is disconnected")
        info = self.client.publish(topic, payload=payload, qos=qos, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed with rc={info.rc}")
        await asyncio.to_thread(info.wait_for_publish, 5)

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: object,
        reason_code: object,
        properties: object,
    ) -> None:
        del userdata, flags, properties
        self._last_connection_reason = str(reason_code)
        if int(reason_code) != 0:
            self._connected.clear()
            logger.error("DJI MQTT connection rejected: %s", reason_code)
            return

        self._connected.set()
        logger.info("DJI MQTT connected to %s:%s", self.host, self.port)
        for topic in SUBSCRIPTIONS:
            result, _mid = client.subscribe(topic, qos=0)
            if result != mqtt.MQTT_ERR_SUCCESS:
                logger.error(
                    "DJI MQTT subscription failed for %s with rc=%s",
                    topic,
                    result,
                )

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: object,
        disconnect_flags: object,
        reason_code: object,
        properties: object,
    ) -> None:
        del client, userdata, disconnect_flags, properties
        self._connected.clear()
        self._last_connection_reason = str(reason_code)
        logger.warning("DJI MQTT disconnected: %s", reason_code)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
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
