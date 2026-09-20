from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


AIRBORNE_MODES = frozenset({3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 16, 17, 18})
AUTOMATIC_TAKEOFF_MODE = 4
STANDBY_MODE = 0


class FlightDecision(StrEnum):
    NONE = "NONE"
    START = "START"
    END = "END"


@dataclass
class DetectorState:
    active: bool = False
    start_confirmations: int = 0
    landing_confirmations: int = 0


class FlightDetector:
    """Conservative flight-boundary detector for M3-series OSD samples."""

    START_ALTITUDE_M = 1.0
    START_HORIZONTAL_SPEED_MPS = 0.7
    START_VERTICAL_SPEED_MPS = 0.5
    START_CONFIRMATIONS = 2
    LAND_ALTITUDE_M = 0.8
    LAND_HORIZONTAL_SPEED_MPS = 0.5
    LAND_VERTICAL_SPEED_MPS = 0.4
    LAND_CONFIRMATIONS = 3

    def evaluate(self, state: DetectorState, telemetry: dict[str, Any]) -> FlightDecision:
        mode = telemetry.get("mode_code")
        aircraft_state = telemetry.get("aircraft_state")
        if not isinstance(aircraft_state, dict):
            aircraft_state = {}
        is_flying = aircraft_state.get("is_flying")
        landed_state = aircraft_state.get("landed_state")

        altitude = self._number(telemetry.get("relative_altitude_m"), default=0.0)
        horizontal = abs(self._number(telemetry.get("horizontal_speed_mps"), default=0.0))
        vertical = abs(self._number(telemetry.get("vertical_speed_mps"), default=0.0))

        if not state.active:
            state.landing_confirmations = 0
            if mode == AUTOMATIC_TAKEOFF_MODE:
                state.active = True
                state.start_confirmations = 0
                return FlightDecision.START

            airborne_signal = mode in AIRBORNE_MODES or is_flying is True
            moving_airborne = airborne_signal and (
                altitude >= self.START_ALTITUDE_M
                or horizontal >= self.START_HORIZONTAL_SPEED_MPS
                or vertical >= self.START_VERTICAL_SPEED_MPS
            )
            state.start_confirmations = state.start_confirmations + 1 if moving_airborne else 0
            if state.start_confirmations >= self.START_CONFIRMATIONS:
                state.active = True
                state.start_confirmations = 0
                return FlightDecision.START
            return FlightDecision.NONE

        state.start_confirmations = 0
        ground_signal = mode == STANDBY_MODE or is_flying is False or landed_state == 1
        landed = (
            ground_signal
            and altitude <= self.LAND_ALTITUDE_M
            and horizontal <= self.LAND_HORIZONTAL_SPEED_MPS
            and vertical <= self.LAND_VERTICAL_SPEED_MPS
        )
        state.landing_confirmations = state.landing_confirmations + 1 if landed else 0
        if state.landing_confirmations >= self.LAND_CONFIRMATIONS:
            state.active = False
            state.landing_confirmations = 0
            return FlightDecision.END
        return FlightDecision.NONE

    @staticmethod
    def _number(value: Any, *, default: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        return float(value)
