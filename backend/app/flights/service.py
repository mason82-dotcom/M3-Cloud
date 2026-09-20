from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.flights.detector import DetectorState, FlightDecision, FlightDetector
from app.models import Flight, TelemetrySample


@dataclass
class ActiveFlight:
    flight_id: uuid.UUID
    last_latitude: float | None = None
    last_longitude: float | None = None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_008.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius_m * math.asin(min(1.0, math.sqrt(a)))


def point_z(telemetry: dict[str, Any]) -> WKTElement | None:
    latitude = telemetry.get("latitude")
    longitude = telemetry.get("longitude")
    altitude = telemetry.get("ellipsoid_height_m")
    if isinstance(latitude, bool) or not isinstance(latitude, (int, float)):
        return None
    if isinstance(longitude, bool) or not isinstance(longitude, (int, float)):
        return None
    if not (-90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180):
        return None
    z = float(altitude) if isinstance(altitude, (int, float)) and not isinstance(altitude, bool) else 0.0
    return WKTElement(f"POINT Z ({float(longitude)} {float(latitude)} {z})", srid=4326)


class FlightRecorder:
    """Persist OSD samples and derive conservative flight sessions."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions
        self.detector = FlightDetector()
        self._states: dict[str, DetectorState] = {}
        self._active: dict[str, ActiveFlight] = {}

    async def recover_interrupted(self) -> int:
        async with self.sessions() as session:
            result = await session.execute(
                update(Flight)
                .where(Flight.status == "ACTIVE")
                .values(
                    status="INTERRUPTED",
                    ended_at=datetime.now(timezone.utc),
                    end_reason="BACKEND_RESTART",
                )
                .returning(Flight.id)
            )
            recovered = len(result.scalars().all())
            await session.commit()
            return recovered

    async def ingest(self, telemetry: dict[str, Any]) -> None:
        aircraft_sn = telemetry.get("source_sn")
        if not isinstance(aircraft_sn, str) or not aircraft_sn:
            return

        detector_state = self._states.setdefault(aircraft_sn, DetectorState())
        decision = self.detector.evaluate(detector_state, telemetry)
        if decision is FlightDecision.START:
            self._active[aircraft_sn] = await self._start_flight(aircraft_sn, telemetry)

        active = self._active.get(aircraft_sn)
        if active is None:
            return

        await self._append_sample(active, telemetry)
        if decision is FlightDecision.END:
            await self._finish_flight(active, telemetry, end_reason="LANDED")
            self._active.pop(aircraft_sn, None)

    async def _start_flight(self, aircraft_sn: str, telemetry: dict[str, Any]) -> ActiveFlight:
        flight = Flight(
            aircraft_sn=aircraft_sn,
            gateway_sn=self._text(telemetry.get("gateway_sn")),
            dji_track_id=self._text(telemetry.get("track_id")),
            status="ACTIVE",
            started_at=self._recorded_at(telemetry),
            takeoff_position=point_z(telemetry),
            max_relative_altitude_m=self._float(telemetry.get("relative_altitude_m")),
            max_horizontal_speed_mps=self._float(telemetry.get("horizontal_speed_mps")),
            min_battery_percent=self._battery_percent(telemetry),
        )
        async with self.sessions() as session:
            session.add(flight)
            await session.commit()

        return ActiveFlight(
            flight_id=flight.id,
            last_latitude=self._float(telemetry.get("latitude")),
            last_longitude=self._float(telemetry.get("longitude")),
        )

    async def _append_sample(self, active: ActiveFlight, telemetry: dict[str, Any]) -> None:
        latitude = self._float(telemetry.get("latitude"))
        longitude = self._float(telemetry.get("longitude"))
        distance_delta = 0.0
        if (
            latitude is not None
            and longitude is not None
            and active.last_latitude is not None
            and active.last_longitude is not None
        ):
            distance_delta = haversine_m(
                active.last_latitude,
                active.last_longitude,
                latitude,
                longitude,
            )
        if latitude is not None and longitude is not None:
            active.last_latitude = latitude
            active.last_longitude = longitude

        position_state = telemetry.get("position_state")
        if not isinstance(position_state, dict):
            position_state = {}

        aircraft_state = telemetry.get("aircraft_state")
        if not isinstance(aircraft_state, dict):
            aircraft_state = {}
        positioning = aircraft_state.get("positioning")
        if not isinstance(positioning, dict):
            positioning = {}

        convergence = self._text(positioning.get("fix"))
        if convergence in (None, "UNKNOWN"):
            convergence = self._text(positioning.get("convergence"))
        if convergence in (None, "UNKNOWN"):
            convergence = self._text(position_state.get("convergence"))
        battery = telemetry.get("battery")
        if not isinstance(battery, dict):
            battery = {}
        attitude = telemetry.get("attitude")
        if not isinstance(attitude, dict):
            attitude = {}

        sample = TelemetrySample(
            flight_id=active.flight_id,
            recorded_at=self._recorded_at(telemetry),
            source_timestamp_ms=int(telemetry.get("source_timestamp_ms") or 0),
            source=self._text(telemetry.get("recording_source")) or "unknown",
            position=point_z(telemetry),
            relative_altitude_m=self._float(telemetry.get("relative_altitude_m")),
            ellipsoid_height_m=self._float(telemetry.get("ellipsoid_height_m")),
            horizontal_speed_mps=self._float(telemetry.get("horizontal_speed_mps")),
            vertical_speed_mps=self._float(telemetry.get("vertical_speed_mps")),
            heading_deg=self._float(attitude.get("yaw_deg")),
            mode_code=self._int(telemetry.get("mode_code")),
            battery_percent=self._int(battery.get("capacity_percent")),
            position_convergence=convergence,
            gps_satellites=self._int(
                positioning.get("gps_satellites")
                if positioning.get("gps_satellites") is not None
                else position_state.get("gps_satellites")
            ),
            rtk_satellites=self._int(
                positioning.get("rtk_satellites")
                if positioning.get("rtk_satellites") is not None
                else position_state.get("rtk_satellites")
            ),
        )

        altitude = self._float(telemetry.get("relative_altitude_m"))
        speed = self._float(telemetry.get("horizontal_speed_mps"))
        battery_percent = self._battery_percent(telemetry)
        converged_delta = 1 if convergence in {"CONVERGED", "FIXED"} else 0
        total_delta = 1 if convergence not in (None, "UNKNOWN") else 0

        async with self.sessions() as session:
            session.add(sample)
            flight = await session.get(Flight, active.flight_id)
            if flight is None:
                return
            flight.distance_m += distance_delta
            flight.max_relative_altitude_m = self._max_optional(flight.max_relative_altitude_m, altitude)
            flight.max_horizontal_speed_mps = self._max_optional(flight.max_horizontal_speed_mps, speed)
            flight.min_battery_percent = self._min_optional(flight.min_battery_percent, battery_percent)
            flight.rtk_converged_samples += converged_delta
            flight.rtk_total_samples += total_delta
            await session.commit()

    async def _finish_flight(
        self,
        active: ActiveFlight,
        telemetry: dict[str, Any],
        *,
        end_reason: str,
    ) -> None:
        ended_at = self._recorded_at(telemetry)
        async with self.sessions() as session:
            flight = await session.get(Flight, active.flight_id)
            if flight is None:
                return
            flight.status = "COMPLETED"
            flight.ended_at = ended_at
            flight.duration_s = max(0.0, (ended_at - flight.started_at).total_seconds())
            flight.landing_position = point_z(telemetry)
            flight.end_reason = end_reason

            ordered = (
                select(TelemetrySample.position.label("position"))
                .where(
                    TelemetrySample.flight_id == active.flight_id,
                    TelemetrySample.position.is_not(None),
                )
                .order_by(TelemetrySample.recorded_at, TelemetrySample.id)
                .subquery()
            )
            point_count = await session.scalar(select(func.count()).select_from(ordered))
            if point_count and point_count >= 2:
                flight.path = await session.scalar(select(func.ST_MakeLine(ordered.c.position)))
            await session.commit()

    @staticmethod
    def _recorded_at(telemetry: dict[str, Any]) -> datetime:
        timestamp_ms = telemetry.get("source_timestamp_ms")
        if isinstance(timestamp_ms, int) and timestamp_ms > 0:
            return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        return datetime.now(timezone.utc)

    @staticmethod
    def _text(value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _float(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @staticmethod
    def _int(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    @classmethod
    def _battery_percent(cls, telemetry: dict[str, Any]) -> int | None:
        battery = telemetry.get("battery")
        if not isinstance(battery, dict):
            return None
        return cls._int(battery.get("capacity_percent"))

    @staticmethod
    def _max_optional(current: float | None, candidate: float | None) -> float | None:
        if candidate is None:
            return current
        return candidate if current is None else max(current, candidate)

    @staticmethod
    def _min_optional(current: int | None, candidate: int | None) -> int | None:
        if candidate is None:
            return current
        return candidate if current is None else min(current, candidate)
