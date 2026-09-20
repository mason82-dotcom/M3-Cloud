from datetime import datetime, timezone
import uuid

import pytest
from geoalchemy2.elements import WKTElement
from sqlalchemy import delete

from app.database import session_factory
from app.media.matching import match_flight_by_capture_window
from app.models import Flight, TelemetrySample


@pytest.mark.asyncio(loop_scope="session")
async def test_gps_confirms_unique_time_candidate() -> None:
    async with session_factory() as session:
        await session.execute(delete(TelemetrySample))
        await session.execute(delete(Flight))
        await session.commit()

        flight = Flight(
            aircraft_sn="M3E-GPS",
            status="COMPLETED",
            started_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 9, 20, 12, 5, tzinfo=timezone.utc),
            distance_m=0.0,
            rtk_converged_samples=0,
            rtk_total_samples=0,
        )
        session.add(flight)
        await session.flush()

        for index, latitude in enumerate((49.0000, 49.0005, 49.0010)):
            session.add(
                TelemetrySample(
                    flight_id=flight.id,
                    recorded_at=datetime(2026, 9, 20, 12, index, tzinfo=timezone.utc),
                    source_timestamp_ms=1_800_000_000_000 + index * 60_000,
                    source="lyrebird",
                    position=WKTElement(f"POINT Z (8.0 {latitude} 150)", srid=4326),
                )
            )
        await session.commit()
        flight_id = flight.id

        match = await match_flight_by_capture_window(
            session,
            capture_started_at=datetime(2026, 9, 20, 12, 1, tzinfo=timezone.utc),
            capture_ended_at=datetime(2026, 9, 20, 12, 2, tzinfo=timezone.utc),
            margin_seconds=30,
            gps_points=[(49.0004, 8.00002), (49.0008, 7.99998)],
            max_distance_m=50,
            min_gps_fraction=0.8,
        )

    assert match.status == "MATCHED_TIME_GPS"
    assert match.flight_id == flight_id
    candidate = match.details["candidates"][0]
    assert candidate["spatial_pass"] is True
    assert candidate["gps_within_fraction"] == 1.0
    assert candidate["median_distance_m"] < 10


@pytest.mark.asyncio(loop_scope="session")
async def test_gps_rejects_time_candidate_at_wrong_location() -> None:
    async with session_factory() as session:
        await session.execute(delete(TelemetrySample))
        await session.execute(delete(Flight))
        await session.commit()

        flight = Flight(
            aircraft_sn="M3E-WRONG-PLACE",
            status="COMPLETED",
            started_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 9, 20, 12, 5, tzinfo=timezone.utc),
            distance_m=0.0,
            rtk_converged_samples=0,
            rtk_total_samples=0,
        )
        session.add(flight)
        await session.flush()
        session.add(
            TelemetrySample(
                flight_id=flight.id,
                recorded_at=datetime(2026, 9, 20, 12, 1, tzinfo=timezone.utc),
                source_timestamp_ms=1_800_000_000_000,
                source="dji_cloud",
                position=WKTElement("POINT Z (8.0 49.0 150)", srid=4326),
            )
        )
        await session.commit()

        match = await match_flight_by_capture_window(
            session,
            capture_started_at=datetime(2026, 9, 20, 12, 1, tzinfo=timezone.utc),
            capture_ended_at=datetime(2026, 9, 20, 12, 2, tzinfo=timezone.utc),
            margin_seconds=30,
            gps_points=[(49.1, 8.1)],
            max_distance_m=100,
            min_gps_fraction=0.8,
        )

    assert match.status == "GPS_REJECTED"
    assert match.flight_id is None
    assert len(match.candidate_ids) == 1
    assert match.details["candidates"][0]["spatial_pass"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_time_only_match_is_explicit_when_dataset_has_no_gps() -> None:
    async with session_factory() as session:
        await session.execute(delete(TelemetrySample))
        await session.execute(delete(Flight))
        await session.commit()

        flight = Flight(
            aircraft_sn="M3E-TIME-ONLY",
            status="COMPLETED",
            started_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 9, 20, 12, 5, tzinfo=timezone.utc),
            distance_m=0.0,
            rtk_converged_samples=0,
            rtk_total_samples=0,
        )
        session.add(flight)
        await session.commit()

        match = await match_flight_by_capture_window(
            session,
            capture_started_at=datetime(2026, 9, 20, 12, 1, tzinfo=timezone.utc),
            capture_ended_at=datetime(2026, 9, 20, 12, 2, tzinfo=timezone.utc),
            margin_seconds=30,
            gps_points=[],
        )

    assert match.status == "MATCHED_TIME_ONLY"
    assert match.flight_id == flight.id
    assert match.details["validation"] == "TIME_ONLY"



@pytest.mark.asyncio(loop_scope="session")
async def test_gps_resolves_ambiguous_time_window() -> None:
    async with session_factory() as session:
        await session.execute(delete(TelemetrySample))
        await session.execute(delete(Flight))
        await session.commit()

        near = Flight(
            aircraft_sn="M3E-NEAR",
            status="COMPLETED",
            started_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 9, 20, 12, 5, tzinfo=timezone.utc),
            distance_m=0.0,
            rtk_converged_samples=0,
            rtk_total_samples=0,
        )
        far = Flight(
            aircraft_sn="M3E-FAR",
            status="COMPLETED",
            started_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 9, 20, 12, 5, tzinfo=timezone.utc),
            distance_m=0.0,
            rtk_converged_samples=0,
            rtk_total_samples=0,
        )
        session.add_all([near, far])
        await session.flush()
        session.add_all(
            [
                TelemetrySample(
                    flight_id=near.id,
                    recorded_at=datetime(2026, 9, 20, 12, 1, tzinfo=timezone.utc),
                    source_timestamp_ms=1_800_000_000_000,
                    source="lyrebird",
                    position=WKTElement("POINT Z (8.0 49.0 150)", srid=4326),
                ),
                TelemetrySample(
                    flight_id=far.id,
                    recorded_at=datetime(2026, 9, 20, 12, 1, tzinfo=timezone.utc),
                    source_timestamp_ms=1_800_000_000_000,
                    source="lyrebird",
                    position=WKTElement("POINT Z (9.0 50.0 150)", srid=4326),
                ),
            ]
        )
        await session.commit()
        near_id = near.id

        match = await match_flight_by_capture_window(
            session,
            capture_started_at=datetime(2026, 9, 20, 12, 1, tzinfo=timezone.utc),
            capture_ended_at=datetime(2026, 9, 20, 12, 2, tzinfo=timezone.utc),
            margin_seconds=30,
            gps_points=[(49.0001, 8.0001)],
            max_distance_m=100,
            min_gps_fraction=0.8,
        )

    assert match.status == "MATCHED_TIME_GPS"
    assert match.flight_id == near_id
    assert len(match.candidate_ids) == 2
    assert sum(
        1 for item in match.details["candidates"] if item["spatial_pass"]
    ) == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_dataset_gps_requires_flight_track_for_auto_assignment() -> None:
    async with session_factory() as session:
        await session.execute(delete(TelemetrySample))
        await session.execute(delete(Flight))
        await session.commit()

        flight = Flight(
            aircraft_sn="M3E-NO-TRACK",
            status="COMPLETED",
            started_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 9, 20, 12, 5, tzinfo=timezone.utc),
            distance_m=0.0,
            rtk_converged_samples=0,
            rtk_total_samples=0,
        )
        session.add(flight)
        await session.commit()
        flight_id = flight.id

        match = await match_flight_by_capture_window(
            session,
            capture_started_at=datetime(2026, 9, 20, 12, 1, tzinfo=timezone.utc),
            capture_ended_at=datetime(2026, 9, 20, 12, 2, tzinfo=timezone.utc),
            margin_seconds=30,
            gps_points=[(49.0, 8.0)],
            max_distance_m=100,
            min_gps_fraction=0.8,
        )

    assert match.status == "GPS_UNVERIFIED"
    assert match.flight_id is None
    assert match.candidate_ids == (flight_id,)
    assert match.details["candidates"][0]["spatial_status"] == "NO_FLIGHT_GPS"



@pytest.mark.asyncio(loop_scope="session")
async def test_timed_gps_rejects_location_seen_only_later_in_same_flight() -> None:
    async with session_factory() as session:
        await session.execute(delete(TelemetrySample))
        await session.execute(delete(Flight))
        await session.commit()

        flight = Flight(
            aircraft_sn="M3E-TIMED-GPS",
            status="COMPLETED",
            started_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 9, 20, 12, 5, tzinfo=timezone.utc),
            distance_m=0.0,
            rtk_converged_samples=0,
            rtk_total_samples=0,
        )
        session.add(flight)
        await session.flush()
        session.add_all(
            [
                TelemetrySample(
                    flight_id=flight.id,
                    recorded_at=datetime(2026, 9, 20, 12, 1, tzinfo=timezone.utc),
                    source_timestamp_ms=1_800_000_000_000,
                    source="lyrebird",
                    position=WKTElement("POINT Z (8.0 49.0 150)", srid=4326),
                ),
                TelemetrySample(
                    flight_id=flight.id,
                    recorded_at=datetime(2026, 9, 20, 12, 4, tzinfo=timezone.utc),
                    source_timestamp_ms=1_800_000_180_000,
                    source="lyrebird",
                    position=WKTElement("POINT Z (8.1 49.1 150)", srid=4326),
                ),
            ]
        )
        await session.commit()

        # The image GPS is near the 12:04 track point, but its image timestamp is 12:01.
        # Whole-track proximity alone would pass; time-coupled GPS must reject it.
        match = await match_flight_by_capture_window(
            session,
            capture_started_at=datetime(2026, 9, 20, 12, 1, tzinfo=timezone.utc),
            capture_ended_at=datetime(2026, 9, 20, 12, 1, 30, tzinfo=timezone.utc),
            margin_seconds=30,
            capture_points=[
                (datetime(2026, 9, 20, 12, 1, tzinfo=timezone.utc), 49.1, 8.1),
            ],
            max_distance_m=100,
            min_gps_fraction=0.8,
            max_sample_time_delta_seconds=5,
        )

    assert match.status == "GPS_REJECTED"
    candidate = match.details["candidates"][0]
    assert candidate["validation_mode"] == "TIMED_GPS"
    assert candidate["timed_points_paired"] == 1
    assert candidate["median_time_delta_s"] == 0.0
    assert candidate["median_distance_m"] > 1000


@pytest.mark.asyncio(loop_scope="session")
async def test_timed_gps_requires_nearby_flight_sample_in_time() -> None:
    async with session_factory() as session:
        await session.execute(delete(TelemetrySample))
        await session.execute(delete(Flight))
        await session.commit()

        flight = Flight(
            aircraft_sn="M3E-TIME-GAP",
            status="COMPLETED",
            started_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 9, 20, 12, 5, tzinfo=timezone.utc),
            distance_m=0.0,
            rtk_converged_samples=0,
            rtk_total_samples=0,
        )
        session.add(flight)
        await session.flush()
        session.add(
            TelemetrySample(
                flight_id=flight.id,
                recorded_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
                source_timestamp_ms=1_800_000_000_000,
                source="dji_cloud",
                position=WKTElement("POINT Z (8.0 49.0 150)", srid=4326),
            )
        )
        await session.commit()

        match = await match_flight_by_capture_window(
            session,
            capture_started_at=datetime(2026, 9, 20, 12, 2, tzinfo=timezone.utc),
            capture_ended_at=datetime(2026, 9, 20, 12, 2, tzinfo=timezone.utc),
            margin_seconds=30,
            capture_points=[
                (datetime(2026, 9, 20, 12, 2, tzinfo=timezone.utc), 49.0, 8.0),
            ],
            max_distance_m=100,
            min_gps_fraction=0.8,
            max_sample_time_delta_seconds=5,
        )

    assert match.status == "GPS_REJECTED"
    candidate = match.details["candidates"][0]
    assert candidate["timed_points_sampled"] == 1
    assert candidate["timed_points_paired"] == 0
    assert candidate["median_time_delta_s"] == 120.0
    assert candidate["median_distance_m"] is None
