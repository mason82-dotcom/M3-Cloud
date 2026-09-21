import pytest

from app.vehicles.base import VehicleSnapshot
from app.vehicles.registry import VehicleRegistry


class Provider:
    def __init__(self, source, vehicles):
        self.source = source
        self._vehicles = vehicles

    async def list_vehicles(self):
        return self._vehicles


@pytest.mark.asyncio
async def test_registry_uses_dji_cloud_as_primary_and_keeps_lyrebird_rtk_fact():
    dji = VehicleSnapshot(
        id="vehicle:A",
        sn="A",
        name="DJI_MAVIC_3E",
        model="DJI_MAVIC_3E",
        source="dji_cloud",
        sources=("dji_cloud",),
        online=True,
        gateway_sn="RC-A",
        updated_at_ms=1000,
        telemetry={
            "home_latitude": 49.0,
            "battery": {"capacity_percent": 80, "remain_flight_time_s": 600},
            "aircraft_state": {
                "source": "dji_cloud",
                "positioning": {
                    "convergence": "CONVERGED",
                    "quality": 5,
                    "fix": "UNKNOWN",
                    "position_source": "DJI_CLOUD",
                    "rtk": {
                        "fix": "UNKNOWN",
                        "convergence": "CONVERGED",
                        "quality": 5,
                    },
                },
            },
        },
    )
    lyrebird = VehicleSnapshot(
        id="vehicle:A",
        sn="A",
        name="field-drone",
        model="M3E",
        source="lyrebird",
        sources=("lyrebird",),
        online=True,
        updated_at_ms=900,
        telemetry={
            "battery": {"capacity_percent": 79},
            "aircraft_state": {
                "source": "lyrebird",
                "positioning": {
                    "fix": "FIXED",
                    "position_source": "RTK_FUSED",
                    "rtk_fixed": True,
                    "rtk": {
                        "fix": "FIXED",
                        "connected": True,
                        "healthy": True,
                    },
                },
            },
        },
    )

    registry = VehicleRegistry([
        Provider("dji_cloud", [dji]),
        Provider("lyrebird", [lyrebird]),
    ])
    vehicles = await registry.list_vehicles()

    assert len(vehicles) == 1
    vehicle = vehicles[0]
    assert vehicle.id == "vehicle:A"
    assert vehicle.sn == "A"
    assert vehicle.source == "dji_cloud"
    assert vehicle.sources == ("dji_cloud", "lyrebird")
    assert vehicle.name == "DJI_MAVIC_3E"
    assert vehicle.model == "DJI_MAVIC_3E"
    assert vehicle.gateway_sn == "RC-A"

    # DJI Cloud remains authoritative where it has a value.
    assert vehicle.telemetry["home_latitude"] == 49.0
    assert vehicle.telemetry["battery"] == {
        "capacity_percent": 80,
        "remain_flight_time_s": 600,
    }
    positioning = vehicle.telemetry["aircraft_state"]["positioning"]
    assert vehicle.telemetry["aircraft_state"]["source"] == "dji_cloud"
    assert positioning["convergence"] == "CONVERGED"
    assert positioning["quality"] == 5

    # MSDK/RTK supplements a fact that Pilot-to-Cloud does not expose.
    assert positioning["fix"] == "FIXED"
    assert positioning["position_source"] == "RTK_FUSED"
    assert positioning["rtk_fixed"] is True
    assert positioning["rtk"]["fix"] == "FIXED"
    assert positioning["rtk"]["connected"] is True
