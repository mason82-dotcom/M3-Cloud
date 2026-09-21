import pytest

from app.dji.gateway import (
    DJIGatewayService,
    DJIUnsupportedGateway,
)


class FakeRegistry:
    def __init__(self, devices, children):
        self.devices = devices
        self.children = children

    async def get_device(self, sn):
        return self.devices.get(sn)

    async def list_children(self, gateway_sn):
        return self.children.get(gateway_sn, [])


class FakeTelemetry:
    def __init__(self, states):
        self.states = states

    async def get(self, sn):
        return self.states.get(sn)


@pytest.mark.asyncio
async def test_rc_pro_gateway_snapshot_keeps_gateway_state_and_aircraft():
    gateway = {
        "sn": "RC123",
        "role": "gateway",
        "type": 144,
        "sub_type": 0,
        "online": True,
        "gateway_sn": "RC123",
    }
    aircraft = {
        "sn": "M3T123",
        "role": "aircraft",
        "type": 77,
        "sub_type": 1,
        "online": True,
        "gateway_sn": "RC123",
    }
    service = DJIGatewayService(
        FakeRegistry({"RC123": gateway}, {"RC123": [aircraft]}),
        FakeTelemetry(
            {
                "RC123": {
                    "capacity_percent": 65,
                    "live_capacity": {"available_video_number": 2},
                    "wireless_link": {"sdr_quality": 4},
                }
            }
        ),
    )

    snapshot = await service.get("RC123")

    assert snapshot.identity["type"] == 144
    assert snapshot.thing_state["capacity_percent"] == 65
    assert snapshot.thing_state["live_capacity"]["available_video_number"] == 2
    assert snapshot.aircraft == (aircraft,)


@pytest.mark.asyncio
async def test_aircraft_cannot_be_treated_as_rc_pro_gateway():
    service = DJIGatewayService(
        FakeRegistry(
            {
                "M3E123": {
                    "sn": "M3E123",
                    "role": "aircraft",
                    "type": 77,
                    "sub_type": 0,
                    "online": True,
                    "gateway_sn": "RC123",
                }
            },
            {},
        ),
        FakeTelemetry({}),
    )

    with pytest.raises(DJIUnsupportedGateway):
        await service.get("M3E123")
