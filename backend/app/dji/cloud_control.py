from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.config import Settings
from app.dji.gateway import DJIGatewayService
from app.dji.services import DJIServiceClient, DJIServiceResponse


class DJICloudControlError(RuntimeError):
    pass


class DJICloudControlNotAuthorized(DJICloudControlError):
    pass


class DJICloudControlConfigError(DJICloudControlError):
    pass


class DJICloudControlGatewayOffline(DJICloudControlError):
    pass


@dataclass(frozen=True)
class DJIDRCBroker:
    address: str
    client_id: str
    username: str
    password: str
    expire_time: int
    enable_tls: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "address": self.address,
            "client_id": self.client_id,
            "username": self.username,
            "password": self.password,
            "expire_time": self.expire_time,
            "enable_tls": self.enable_tls,
        }


def _validate_broker_address(address: str) -> str:
    value = address.strip()
    if not value or "://" in value or any(char.isspace() for char in value):
        raise DJICloudControlConfigError(
            "DJI DRC broker address must use host:port without a URL scheme"
        )
    try:
        parsed = urlsplit(f"//{value}")
        port = parsed.port
    except ValueError as exc:
        raise DJICloudControlConfigError(
            "DJI DRC broker address contains an invalid port"
        ) from exc
    if not parsed.hostname or port is None or not 1 <= port <= 65535:
        raise DJICloudControlConfigError(
            "DJI DRC broker address must include a valid host and port"
        )
    return value


def drc_broker_for(
    settings: Settings,
    *,
    gateway_sn: str,
    now_s: int | None = None,
) -> DJIDRCBroker:
    address = _validate_broker_address(settings.dji_drc_broker_address)
    username = settings.dji_drc_username.strip()
    password = settings.dji_drc_password
    prefix = settings.dji_drc_client_id_prefix.strip()

    if not username or not password:
        raise DJICloudControlConfigError(
            "DJI DRC broker username/password are not configured"
        )
    if not prefix:
        raise DJICloudControlConfigError(
            "DJI DRC client id prefix is not configured"
        )

    issued_at = int(time.time()) if now_s is None else int(now_s)
    return DJIDRCBroker(
        address=address,
        client_id=f"{prefix}{gateway_sn}",
        username=username,
        password=password,
        expire_time=issued_at + int(settings.dji_drc_credential_ttl_seconds),
        enable_tls=bool(settings.dji_drc_enable_tls),
    )


def _response(value: DJIServiceResponse) -> dict[str, object]:
    return {
        "gateway_sn": value.gateway_sn,
        "method": value.method,
        "tid": value.tid,
        "bid": value.bid,
        "result": value.result,
        "output": value.output,
    }


class DJICloudControl:
    """DJI Pilot 2 cloud-control authorization and DRC link handshake.

    This domain deliberately does not issue aircraft movement commands. It only
    establishes/relinquishes authority and the DRC transport preconditions.
    """

    def __init__(
        self,
        services: DJIServiceClient,
        gateways: DJIGatewayService,
        settings: Settings,
    ) -> None:
        self.services = services
        self.gateways = gateways
        self.settings = settings

    async def _gateway(self, gateway_sn: str):
        snapshot = await self.gateways.get(gateway_sn)
        if snapshot.identity.get("online") is not True:
            raise DJICloudControlGatewayOffline(
                f"DJI gateway is offline: {gateway_sn}"
            )
        return snapshot

    async def request_authorization(
        self,
        gateway_sn: str,
        *,
        user_id: str,
        user_callsign: str,
    ) -> dict[str, object]:
        await self._gateway(gateway_sn)
        response = await self.services.call(
            gateway_sn,
            "cloud_control_auth_request",
            {
                "user_id": user_id,
                "user_callsign": user_callsign,
                "control_keys": ["flight"],
            },
        )
        return _response(response)

    async def release(self, gateway_sn: str) -> dict[str, object]:
        await self._gateway(gateway_sn)
        response = await self.services.call(
            gateway_sn,
            "cloud_control_release",
            {"control_keys": ["flight"]},
        )
        return _response(response)

    async def enter_drc(self, gateway_sn: str) -> dict[str, object]:
        snapshot = await self._gateway(gateway_sn)
        state = snapshot.thing_state or {}
        authorized = state.get("is_cloud_control_auth")
        if authorized not in (True, 1):
            raise DJICloudControlNotAuthorized(
                "DJI cloud flight-control authority has not been granted"
            )

        broker = drc_broker_for(
            self.settings,
            gateway_sn=gateway_sn,
        )
        response = await self.services.call(
            gateway_sn,
            "drc_mode_enter",
            {
                "mqtt_broker": broker.as_dict(),
                "osd_frequency": self.settings.dji_drc_osd_frequency_hz,
                "hsi_frequency": self.settings.dji_drc_hsi_frequency_hz,
            },
        )
        return _response(response)
