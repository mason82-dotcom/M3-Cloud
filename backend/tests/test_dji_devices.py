import pytest

from app.dji.devices import (
    DJIDeviceOffline,
    DJIDeviceService,
    DJIPropertySetRejected,
    DJIUnsupportedDevice,
)
from app.dji.properties import DJIPropertySetResponse
from app.dji.protocol import CorrelatedMessage


class FakeRegistry:
    def __init__(self, devices):
        self.devices = devices

    async def get_device(self, sn):
        return self.devices.get(sn)


class FakeTelemetry:
    def __init__(self, state=None):
        self.state = state

    async def get(self, sn):
        del sn
        return self.state


class FakeProperties:
    def __init__(self, results=None):
        self.calls = []
        self.results = results

    async def set(self, gateway_sn, properties):
        self.calls.append((gateway_sn, properties))
        results = self.results if self.results is not None else {
            name: 0 for name in properties
        }
        return DJIPropertySetResponse(
            gateway_sn=gateway_sn,
            tid="tid",
            bid="bid",
            results=results,
            message=CorrelatedMessage(
                tid="tid",
                bid="bid",
                timestamp=1,
                data={
                    name: {"result": result}
                    for name, result in results.items()
                },
            ),
        )


def m3_identity(**updates):
    value = {
        "sn": "M3T123",
        "role": "aircraft",
        "type": 77,
        "sub_type": 1,
        "online": True,
        "gateway_sn": "RC123",
    }
    value.update(updates)
    return value


@pytest.mark.asyncio
async def test_device_snapshot_combines_registry_identity_and_thing_state():
    service = DJIDeviceService(
        FakeRegistry({"M3T123": m3_identity()}),
        FakeTelemetry({"dji_properties": {"mode_code": 3}}),
        FakeProperties(),
    )

    snapshot = await service.get("M3T123")

    assert snapshot.identity["gateway_sn"] == "RC123"
    assert snapshot.thing_state["dji_properties"]["mode_code"] == 3


@pytest.mark.asyncio
async def test_m3_property_set_routes_aircraft_via_pilot_gateway():
    properties = FakeProperties()
    service = DJIDeviceService(
        FakeRegistry({"M3T123": m3_identity()}),
        FakeTelemetry(),
        properties,
    )

    response = await service.set_m3_properties(
        "M3T123",
        {
            "height_limit": 120,
            "night_lights_state": 1,
        },
    )

    assert response.ok is True
    assert properties.calls == [
        (
            "RC123",
            {
                "height_limit": 120,
                "night_lights_state": 1,
            },
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("sub_type", [0, 1, 2])
async def test_all_m3_variants_use_same_validated_property_transport(sub_type):
    properties = FakeProperties()
    service = DJIDeviceService(
        FakeRegistry({"AIR": m3_identity(sn="AIR", sub_type=sub_type)}),
        FakeTelemetry(),
        properties,
    )

    await service.set_m3_properties("AIR", {"height_limit": 100})

    assert properties.calls[0][0] == "RC123"
    assert properties.calls[0][1] == {"height_limit": 100}


@pytest.mark.asyncio
async def test_non_m3_device_cannot_use_m3_property_path():
    service = DJIDeviceService(
        FakeRegistry(
            {
                "RC123": {
                    "sn": "RC123",
                    "role": "gateway",
                    "type": 144,
                    "sub_type": 0,
                    "online": True,
                    "gateway_sn": "RC123",
                }
            }
        ),
        FakeTelemetry(),
        FakeProperties(),
    )

    with pytest.raises(DJIUnsupportedDevice):
        await service.set_m3_properties("RC123", {"height_limit": 120})


@pytest.mark.asyncio
async def test_offline_aircraft_is_rejected_before_publish():
    properties = FakeProperties()
    service = DJIDeviceService(
        FakeRegistry({"M3T123": m3_identity(online=False)}),
        FakeTelemetry(),
        properties,
    )

    with pytest.raises(DJIDeviceOffline):
        await service.set_m3_properties("M3T123", {"height_limit": 120})

    assert properties.calls == []


@pytest.mark.asyncio
async def test_property_reply_must_cover_exact_requested_set():
    properties = FakeProperties(results={"height_limit": 0})
    service = DJIDeviceService(
        FakeRegistry({"M3T123": m3_identity()}),
        FakeTelemetry(),
        properties,
    )

    with pytest.raises(DJIPropertySetRejected) as exc_info:
        await service.set_m3_properties(
            "M3T123",
            {
                "height_limit": 120,
                "night_lights_state": 1,
            },
        )

    assert exc_info.value.missing == {"night_lights_state"}


@pytest.mark.asyncio
async def test_nonzero_dji_property_result_is_rejected():
    service = DJIDeviceService(
        FakeRegistry({"M3T123": m3_identity()}),
        FakeTelemetry(),
        FakeProperties(results={"height_limit": 1}),
    )

    with pytest.raises(DJIPropertySetRejected) as exc_info:
        await service.set_m3_properties("M3T123", {"height_limit": 120})

    assert exc_info.value.failed == {"height_limit": 1}



@pytest.mark.asyncio
async def test_payload_context_uses_live_dji_camera_index():
    service = DJIDeviceService(
        FakeRegistry({"M3T123": m3_identity()}),
        FakeTelemetry(
            {
                "cameras": [
                    {
                        "payload_index": "67-0-0",
                        "wide_exposure_mode": 1,
                        "ir_metering_mode": 0,
                    }
                ]
            }
        ),
        FakeProperties(),
    )

    context = await service.resolve_payload_context("M3T123")

    assert context.gateway_sn == "RC123"
    assert context.m3_sub_type == 1
    assert context.payload_index == "67-0-0"
    assert context.camera_state["ir_metering_mode"] == 0


@pytest.mark.asyncio
async def test_payload_context_rejects_cross_model_payload_index():
    service = DJIDeviceService(
        FakeRegistry({"M3T123": m3_identity()}),
        FakeTelemetry({"cameras": [{"payload_index": "66-0-0"}]}),
        FakeProperties(),
    )

    with pytest.raises(ValueError, match="expected payload type 67"):
        await service.resolve_payload_context("M3T123")
