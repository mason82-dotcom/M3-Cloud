from app.vehicles.base import VehicleSnapshot
from app.vehicles.registry import VehicleRegistry


class Provider:
    def __init__(self, source, vehicles):
        self.source = source
        self._vehicles = vehicles

    async def list_vehicles(self):
        return self._vehicles


async def test_registry_prefers_fresher_vehicle_for_same_sn():
    older = VehicleSnapshot(id="dji:A", sn="A", name="A", model="M3E", source="dji_cloud", online=True, updated_at_ms=10)
    newer = VehicleSnapshot(id="lyrebird:A", sn="A", name="A", model="M3E", source="lyrebird", online=True, updated_at_ms=20)
    registry = VehicleRegistry([Provider("dji_cloud", [older]), Provider("lyrebird", [newer])])
    vehicles = await registry.list_vehicles()
    assert len(vehicles) == 1
    assert vehicles[0].source == "lyrebird"
