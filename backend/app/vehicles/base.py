from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class VehicleSnapshot:
    """Protocol-neutral vehicle state exposed to the M3-Cloud UI."""

    id: str
    sn: str
    name: str
    model: str
    source: str
    online: bool
    gateway_sn: str | None = None
    updated_at_ms: int | None = None
    telemetry: dict[str, Any] | None = None
    sources: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class VehicleProvider(Protocol):
    source: str

    async def list_vehicles(self) -> list[VehicleSnapshot]:
        ...


def canonical_vehicle_id(serial: str) -> str:
    """Stable source-neutral ID for an aircraft with a known DJI serial."""

    return f"vehicle:{serial}"
