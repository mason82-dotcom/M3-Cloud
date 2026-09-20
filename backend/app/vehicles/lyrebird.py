from __future__ import annotations

from app.vehicles.base import VehicleSnapshot


class LyrebirdVehicleProvider:
    """Adapter boundary for Lyrebird.

    Lyrebird remains an independent subsystem. Its HTTP/MAVLink bridge will be
    connected here without coupling the UI to Lyrebird-specific payloads.
    """

    source = "lyrebird"

    async def list_vehicles(self) -> list[VehicleSnapshot]:
        return []
