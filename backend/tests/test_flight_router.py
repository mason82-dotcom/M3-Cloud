import pytest

from app.flights.router import FlightTelemetryRouter
from app.vehicles.base import VehicleSnapshot


class Recorder:
    def __init__(self):
        self.samples = []

    async def ingest(self, telemetry):
        self.samples.append(telemetry)


@pytest.mark.asyncio
async def test_lyrebird_preempts_dji_for_same_serial() -> None:
    recorder = Recorder()
    router = FlightTelemetryRouter(
        recorder,
        lyrebird_preference_seconds=30.0,
        lyrebird_min_interval_ms=0,
    )

    await router.ingest(
        {
            "source_sn": "AIRCRAFT-A",
            "source_timestamp_ms": 1000,
            "mode_code": 3,
            "relative_altitude_m": 10.0,
            "horizontal_speed_mps": 2.0,
        }
    )

    await router.ingest_vehicle(
        VehicleSnapshot(
            id="vehicle:AIRCRAFT-A",
            sn="AIRCRAFT-A",
            name="field",
            model="M3E",
            source="lyrebird",
            sources=("lyrebird",),
            online=True,
            telemetry={
                "last_seen_ms": 2000,
                "latitude": 49.0,
                "longitude": 8.0,
                "relative_altitude_m": 11.0,
                "velocity_north_mps": 3.0,
                "velocity_east_mps": 4.0,
                "velocity_down_mps": -1.0,
                "aircraft_state": {
                    "is_flying": True,
                    "landed_state": 2,
                    "positioning": {
                        "fix": "FIXED",
                        "gps_satellites": 22,
                        "rtk_satellites": 30,
                    },
                },
            },
        )
    )

    await router.ingest(
        {
            "source_sn": "AIRCRAFT-A",
            "source_timestamp_ms": 3000,
            "mode_code": 3,
            "relative_altitude_m": 12.0,
            "horizontal_speed_mps": 2.0,
        }
    )

    assert len(recorder.samples) == 2
    assert recorder.samples[0]["recording_source"] == "dji_cloud"
    assert recorder.samples[1]["source_sn"] == "AIRCRAFT-A"
    assert recorder.samples[1]["recording_source"] == "lyrebird"
    assert recorder.samples[1]["horizontal_speed_mps"] == 5.0
    assert recorder.samples[1]["vertical_speed_mps"] == 1.0
    assert recorder.samples[1]["aircraft_state"]["positioning"]["fix"] == "FIXED"


@pytest.mark.asyncio
async def test_unidentified_lyrebird_is_not_persisted() -> None:
    recorder = Recorder()
    router = FlightTelemetryRouter(recorder, lyrebird_min_interval_ms=0)

    await router.ingest_vehicle(
        VehicleSnapshot(
            id="lyrebird:10.0.0.2",
            sn="lyrebird@10.0.0.2",
            name="unknown",
            model="M3E",
            source="lyrebird",
            online=True,
            telemetry={"last_seen_ms": 1000},
        )
    )

    assert recorder.samples == []
