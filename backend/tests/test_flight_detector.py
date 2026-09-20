import uuid

import pytest
from sqlalchemy import delete, func, select

from app.database import session_factory
from app.flights.detector import DetectorState, FlightDecision, FlightDetector
from app.flights.service import FlightRecorder, haversine_m
from app.models import Flight, TelemetrySample


def sample(*, mode: int, altitude: float = 0.0, horizontal: float = 0.0, vertical: float = 0.0):
    return {
        "mode_code": mode,
        "relative_altitude_m": altitude,
        "horizontal_speed_mps": horizontal,
        "vertical_speed_mps": vertical,
    }


def test_automatic_takeoff_starts_immediately() -> None:
    detector = FlightDetector()
    state = DetectorState()
    assert detector.evaluate(state, sample(mode=4)) is FlightDecision.START
    assert state.active is True


def test_manual_airborne_start_requires_two_confirmations() -> None:
    detector = FlightDetector()
    state = DetectorState()
    airborne = sample(mode=3, altitude=1.4, horizontal=1.0)
    assert detector.evaluate(state, airborne) is FlightDecision.NONE
    assert detector.evaluate(state, airborne) is FlightDecision.START


def test_noise_does_not_start_flight() -> None:
    detector = FlightDetector()
    state = DetectorState()
    assert detector.evaluate(state, sample(mode=0, altitude=1.2)) is FlightDecision.NONE
    assert detector.evaluate(state, sample(mode=3, altitude=0.2, horizontal=0.1)) is FlightDecision.NONE
    assert state.active is False


def test_landing_requires_three_standby_samples() -> None:
    detector = FlightDetector()
    state = DetectorState(active=True)
    landed = sample(mode=0, altitude=0.2, horizontal=0.1, vertical=0.1)
    assert detector.evaluate(state, landed) is FlightDecision.NONE
    assert detector.evaluate(state, landed) is FlightDecision.NONE
    assert detector.evaluate(state, landed) is FlightDecision.END
    assert state.active is False


def test_landing_counter_resets_when_aircraft_moves_again() -> None:
    detector = FlightDetector()
    state = DetectorState(active=True)
    landed = sample(mode=0, altitude=0.2, horizontal=0.1, vertical=0.1)
    assert detector.evaluate(state, landed) is FlightDecision.NONE
    assert detector.evaluate(state, sample(mode=3, altitude=2.0, horizontal=1.0)) is FlightDecision.NONE
    assert detector.evaluate(state, landed) is FlightDecision.NONE


def test_haversine_distance_is_metric() -> None:
    distance = haversine_m(49.0, 8.0, 49.001, 8.0)
    assert 110.0 < distance < 112.5


def flight_sample(
    timestamp_ms: int,
    *,
    mode: int,
    latitude: float,
    longitude: float,
    altitude: float,
    horizontal: float,
    vertical: float = 0.0,
    battery: int = 80,
):
    return {
        "source_sn": "M3E-INTEGRATION-TEST",
        "gateway_sn": "RC-INTEGRATION-TEST",
        "source_timestamp_ms": timestamp_ms,
        "latitude": latitude,
        "longitude": longitude,
        "relative_altitude_m": altitude,
        "ellipsoid_height_m": 150.0 + altitude,
        "horizontal_speed_mps": horizontal,
        "vertical_speed_mps": vertical,
        "mode_code": mode,
        "track_id": "track-integration",
        "battery": {"capacity_percent": battery},
        "attitude": {"yaw_deg": 90.0},
        "position_state": {
            "convergence": "CONVERGED",
            "gps_satellites": 20,
            "rtk_satellites": 30,
        },
    }


@pytest.mark.asyncio
async def test_flight_recorder_persists_completed_postgis_path() -> None:
    async with session_factory() as session:
        await session.execute(delete(TelemetrySample))
        await session.execute(delete(Flight))
        await session.commit()

    recorder = FlightRecorder(session_factory)
    base = 1_800_000_000_000

    await recorder.ingest(
        flight_sample(
            base,
            mode=4,
            latitude=49.0000,
            longitude=8.0000,
            altitude=0.4,
            horizontal=0.2,
        )
    )
    await recorder.ingest(
        flight_sample(
            base + 2_000,
            mode=3,
            latitude=49.0005,
            longitude=8.0000,
            altitude=15.0,
            horizontal=5.0,
            battery=78,
        )
    )

    for offset in (4_000, 6_000, 8_000):
        await recorder.ingest(
            flight_sample(
                base + offset,
                mode=0,
                latitude=49.0010,
                longitude=8.0000,
                altitude=0.2,
                horizontal=0.1,
                vertical=0.1,
                battery=76,
            )
        )

    async with session_factory() as session:
        flights = (await session.scalars(select(Flight))).all()
        assert len(flights) == 1

        flight = flights[0]
        assert flight.status == "COMPLETED"
        assert flight.end_reason == "LANDED"
        assert flight.duration_s == 8.0
        assert flight.distance_m > 100.0
        assert flight.max_relative_altitude_m == 15.0
        assert flight.max_horizontal_speed_mps == 5.0
        assert flight.min_battery_percent == 76
        assert flight.rtk_converged_samples == 5
        assert flight.rtk_total_samples == 5

        sample_count = await session.scalar(
            select(func.count(TelemetrySample.id)).where(TelemetrySample.flight_id == flight.id)
        )
        point_count = await session.scalar(select(func.ST_NPoints(flight.path)))

        assert sample_count == 5
        assert point_count == 5
        assert isinstance(flight.id, uuid.UUID)
