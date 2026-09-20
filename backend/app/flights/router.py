from __future__ import annotations

import math
import time
from typing import Any

from app.flights.service import FlightRecorder
from app.vehicles.base import VehicleSnapshot
from app.vehicles.state import normalize_aircraft_state


class FlightTelemetryRouter:
    """Route multiple telemetry sources into one recorder without duplicate samples."""

    def __init__(
        self,
        recorder: FlightRecorder,
        *,
        lyrebird_preference_seconds: float = 3.0,
        lyrebird_min_interval_ms: int = 1000,
    ):
        self.recorder = recorder
        self.lyrebird_preference_seconds = lyrebird_preference_seconds
        self.lyrebird_min_interval_ms = lyrebird_min_interval_ms
        self._lyrebird_seen: dict[str, float] = {}
        self._last_lyrebird_sample_ms: dict[str, int] = {}

    async def ingest(self, telemetry: dict[str, Any]) -> None:
        """DJI Cloud observer entry point."""

        sample = normalize_aircraft_state(telemetry, source="dji_cloud") or telemetry
        sample["recording_source"] = "dji_cloud"
        aircraft_sn = sample.get("source_sn")
        if not isinstance(aircraft_sn, str) or not aircraft_sn:
            return

        last_lyrebird = self._lyrebird_seen.get(aircraft_sn)
        if (
            last_lyrebird is not None
            and time.monotonic() - last_lyrebird <= self.lyrebird_preference_seconds
        ):
            return

        await self.recorder.ingest(sample)

    async def ingest_vehicle(self, vehicle: VehicleSnapshot) -> None:
        """Lyrebird vehicle entry point using the canonical physical aircraft serial."""

        if vehicle.source != "lyrebird" or vehicle.sn.startswith("lyrebird@"):
            return

        telemetry = vehicle.telemetry
        if not isinstance(telemetry, dict):
            return

        sample = self._lyrebird_sample(vehicle)
        timestamp_ms = sample["source_timestamp_ms"]
        last_sample_ms = self._last_lyrebird_sample_ms.get(vehicle.sn)
        if (
            last_sample_ms is not None
            and timestamp_ms - last_sample_ms < self.lyrebird_min_interval_ms
        ):
            self._lyrebird_seen[vehicle.sn] = time.monotonic()
            return

        self._lyrebird_seen[vehicle.sn] = time.monotonic()
        self._last_lyrebird_sample_ms[vehicle.sn] = timestamp_ms
        await self.recorder.ingest(sample)

    @staticmethod
    def _finite(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        result = float(value)
        return result if math.isfinite(result) else None

    def _lyrebird_sample(self, vehicle: VehicleSnapshot) -> dict[str, Any]:
        telemetry = vehicle.telemetry or {}

        north = self._finite(telemetry.get("velocity_north_mps"))
        east = self._finite(telemetry.get("velocity_east_mps"))
        horizontal = self._finite(telemetry.get("horizontal_speed_mps"))
        if horizontal is None and north is not None and east is not None:
            horizontal = math.hypot(north, east)

        vertical = self._finite(telemetry.get("climb_rate_mps"))
        if vertical is None:
            down = self._finite(telemetry.get("velocity_down_mps"))
            vertical = -down if down is not None else self._finite(telemetry.get("vertical_speed_mps"))

        timestamp_ms = telemetry.get("last_seen_ms")
        if not isinstance(timestamp_ms, int) or timestamp_ms <= 0:
            timestamp_ms = int(time.time() * 1000)

        sample = dict(telemetry)
        sample.update(
            {
                "source_sn": vehicle.sn,
                "gateway_sn": vehicle.gateway_sn,
                "source_timestamp_ms": timestamp_ms,
                "recording_source": "lyrebird",
                "horizontal_speed_mps": horizontal,
                "vertical_speed_mps": vertical,
            }
        )
        return sample
