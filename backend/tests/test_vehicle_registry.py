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
async def test_registry_fuses_dji_and_lyrebird_for_same_physical_serial():
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
                "positioning": {"convergence": "CONVERGED"},
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
                "positioning": {"fix": "FIXED", "position_source": "RTK_FUSED"},
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
    assert vehicle.source == "lyrebird"
    assert vehicle.sources == ("lyrebird", "dji_cloud")
    assert vehicle.name == "field-drone"
    assert vehicle.model == "M3E"
    assert vehicle.gateway_sn == "RC-A"
    assert vehicle.telemetry["home_latitude"] == 49.0
    assert vehicle.telemetry["battery"] == {
        "capacity_percent": 79,
        "remain_flight_time_s": 600,
    }
    assert vehicle.telemetry["aircraft_state"]["positioning"]["fix"] == "FIXED"
    assert vehicle.telemetry["aircraft_state"]["positioning"]["convergence"] == "CONVERGED"
