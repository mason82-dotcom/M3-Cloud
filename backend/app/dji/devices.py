from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.dji.models.m3 import (
    M3ThingModelValidationError,
    is_m3_identity,
    validate_m3_property_patch,
)
from app.dji.properties import DJIPropertyClient, DJIPropertySetResponse
from app.dji.registry import DeviceRegistry
from app.dji.telemetry import TelemetryStore


class DJIDeviceError(RuntimeError):
    pass


class DJIDeviceNotFound(DJIDeviceError):
    pass


class DJIUnsupportedDevice(DJIDeviceError):
    pass


class DJIDeviceOffline(DJIDeviceError):
    pass


class DJIPropertySetRejected(DJIDeviceError):
    def __init__(
        self,
        aircraft_sn: str,
        response: DJIPropertySetResponse,
        *,
        expected_properties: set[str],
    ) -> None:
        missing = expected_properties - set(response.results)
        unexpected = set(response.results) - expected_properties
        failed = {
            name: result
            for name, result in response.results.items()
            if result != 0
        }
        super().__init__(
            "DJI property/set was not fully accepted "
            f"for {aircraft_sn}: failed={failed}, "
            f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )
        self.aircraft_sn = aircraft_sn
        self.response = response
        self.missing = missing
        self.unexpected = unexpected
        self.failed = failed


@dataclass(frozen=True)
class DJIPayloadContext:
    aircraft_sn: str
    gateway_sn: str
    m3_sub_type: int
    payload_index: str
    camera_state: dict[str, Any]


@dataclass(frozen=True)
class DJIDeviceSnapshot:
    identity: dict[str, Any]
    thing_state: dict[str, Any] | None


class DJIDeviceService:
    """Primary DJI Cloud API device domain for Pilot 2 managed aircraft."""

    def __init__(
        self,
        registry: DeviceRegistry,
        telemetry: TelemetryStore,
        properties: DJIPropertyClient,
    ) -> None:
        self.registry = registry
        self.telemetry = telemetry
        self.properties = properties

    async def get(self, sn: str) -> DJIDeviceSnapshot:
        identity = await self.registry.get_device(sn)
        if identity is None:
            raise DJIDeviceNotFound(f"DJI device not found: {sn}")
        return DJIDeviceSnapshot(
            identity=identity,
            thing_state=await self.telemetry.get(sn),
        )

    async def resolve_payload_context(
        self,
        aircraft_sn: str,
        *,
        payload_index: str | None = None,
    ) -> DJIPayloadContext:
        snapshot = await self.get(aircraft_sn)
        identity = snapshot.identity
        if identity.get("role") != "aircraft" or not is_m3_identity(
            identity.get("type"),
            identity.get("sub_type"),
        ):
            raise DJIUnsupportedDevice(
                f"DJI device {aircraft_sn} is not an M3E/M3T/M3M aircraft"
            )
        if identity.get("online") is not True:
            raise DJIDeviceOffline(f"DJI aircraft is offline: {aircraft_sn}")

        gateway_sn = identity.get("gateway_sn")
        sub_type = identity.get("sub_type")
        if not isinstance(gateway_sn, str) or not gateway_sn:
            raise DJIDeviceError(
                f"DJI aircraft {aircraft_sn} has no Pilot 2 gateway association"
            )
        if not isinstance(sub_type, int) or isinstance(sub_type, bool):
            raise DJIUnsupportedDevice(
                f"DJI aircraft {aircraft_sn} has invalid M3 subtype"
            )

        state = snapshot.thing_state or {}
        cameras = state.get("cameras")
        candidates = [
            camera
            for camera in cameras
            if isinstance(camera, dict)
            and isinstance(camera.get("payload_index"), str)
        ] if isinstance(cameras, list) else []

        if payload_index is not None:
            candidates = [
                camera
                for camera in candidates
                if camera["payload_index"] == payload_index
            ]

        if not candidates:
            detail = (
                f"payload {payload_index!r} is not present"
                if payload_index is not None
                else "no DJI camera payload is present in the current thing state"
            )
            raise DJIDeviceError(f"{aircraft_sn}: {detail}")
        if len(candidates) > 1 and payload_index is None:
            raise DJIDeviceError(
                f"{aircraft_sn}: multiple DJI payloads are present; "
                "payload_index must be explicit"
            )

        camera = candidates[0]
        resolved_index = camera["payload_index"]
        from app.dji.models.payload import validate_payload_index

        validate_payload_index(sub_type, resolved_index)
        return DJIPayloadContext(
            aircraft_sn=aircraft_sn,
            gateway_sn=gateway_sn,
            m3_sub_type=sub_type,
            payload_index=resolved_index,
            camera_state=dict(camera),
        )

    async def set_m3_properties(
        self,
        aircraft_sn: str,
        properties: Mapping[str, Any],
    ) -> DJIPropertySetResponse:
        identity = await self.registry.get_device(aircraft_sn)
        if identity is None:
            raise DJIDeviceNotFound(f"DJI aircraft not found: {aircraft_sn}")
        if identity.get("role") != "aircraft" or not is_m3_identity(
            identity.get("type"),
            identity.get("sub_type"),
        ):
            raise DJIUnsupportedDevice(
                f"DJI device {aircraft_sn} is not an M3E/M3T/M3M aircraft"
            )
        if identity.get("online") is not True:
            raise DJIDeviceOffline(f"DJI aircraft is offline: {aircraft_sn}")

        gateway_sn = identity.get("gateway_sn")
        if not isinstance(gateway_sn, str) or not gateway_sn:
            raise DJIDeviceError(
                f"DJI aircraft {aircraft_sn} has no Pilot 2 gateway association"
            )

        try:
            validated = validate_m3_property_patch(properties)
        except M3ThingModelValidationError:
            raise

        # Pilot-to-Cloud property/set is published on the gateway topic. The
        # M3 aircraft identity is resolved above so callers never need to route
        # aircraft properties through the RC Pro manually.
        response = await self.properties.set(gateway_sn, validated)

        expected = set(validated)
        if (
            set(response.results) != expected
            or any(result != 0 for result in response.results.values())
        ):
            raise DJIPropertySetRejected(
                aircraft_sn,
                response,
                expected_properties=expected,
            )
        return response
