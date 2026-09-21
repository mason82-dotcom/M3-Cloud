from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.dji.models.rc_pro import is_rc_pro_enterprise_identity
from app.dji.registry import DeviceRegistry
from app.dji.telemetry import TelemetryStore


class DJIGatewayError(RuntimeError):
    pass


class DJIGatewayNotFound(DJIGatewayError):
    pass


class DJIUnsupportedGateway(DJIGatewayError):
    pass


@dataclass(frozen=True)
class DJIGatewaySnapshot:
    identity: dict[str, Any]
    thing_state: dict[str, Any] | None
    aircraft: tuple[dict[str, Any], ...]


class DJIGatewayService:
    """Primary Pilot 2 / RC Pro Enterprise gateway domain."""

    def __init__(
        self,
        registry: DeviceRegistry,
        telemetry: TelemetryStore,
    ) -> None:
        self.registry = registry
        self.telemetry = telemetry

    async def get(self, gateway_sn: str) -> DJIGatewaySnapshot:
        identity = await self.registry.get_device(gateway_sn)
        if identity is None:
            raise DJIGatewayNotFound(f"DJI gateway not found: {gateway_sn}")
        if identity.get("role") != "gateway" or not is_rc_pro_enterprise_identity(
            identity.get("type"),
            identity.get("sub_type"),
        ):
            raise DJIUnsupportedGateway(
                f"DJI device {gateway_sn} is not an RC Pro Enterprise gateway"
            )

        return DJIGatewaySnapshot(
            identity=identity,
            thing_state=await self.telemetry.get(gateway_sn),
            aircraft=tuple(await self.registry.list_children(gateway_sn)),
        )
