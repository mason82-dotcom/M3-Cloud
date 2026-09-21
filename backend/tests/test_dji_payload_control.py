import pytest

from app.dji.models.payload import DJIPayloadValidationError
from app.dji.payload_control import DJIPayloadControl


class FakeServices:
    def __init__(self):
        self.calls = []

    async def call(self, gateway_sn, method, data):
        self.calls.append((gateway_sn, method, data))
        return {"gateway_sn": gateway_sn, "method": method, "data": data}


@pytest.mark.asyncio
async def test_m3t_infrared_metering_uses_documented_service():
    services = FakeServices()
    payloads = DJIPayloadControl(services)

    await payloads.ir_metering_area_set(
        "RC123",
        m3_sub_type=1,
        payload_index="67-0-0",
        x=0.1,
        y=0.2,
        width=0.3,
        height=0.4,
    )

    assert services.calls == [
        (
            "RC123",
            "ir_metering_area_set",
            {
                "payload_index": "67-0-0",
                "x": 0.1,
                "y": 0.2,
                "width": 0.3,
                "height": 0.4,
            },
        )
    ]


@pytest.mark.asyncio
async def test_m3e_cannot_use_m3t_ir_control():
    services = FakeServices()
    payloads = DJIPayloadControl(services)

    with pytest.raises(DJIPayloadValidationError, match="only valid for the M3T"):
        await payloads.ir_metering_mode_set(
            "RC123",
            m3_sub_type=0,
            payload_index="66-0-0",
            mode=1,
        )

    assert services.calls == []


@pytest.mark.asyncio
async def test_payload_index_cannot_cross_m3_variants():
    services = FakeServices()
    payloads = DJIPayloadControl(services)

    with pytest.raises(DJIPayloadValidationError, match="expected payload type 67"):
        await payloads.photo_take(
            "RC123",
            m3_sub_type=1,
            payload_index="66-0-0",
        )

    assert services.calls == []


@pytest.mark.asyncio
async def test_visible_and_ir_zoom_ranges_are_separate():
    services = FakeServices()
    payloads = DJIPayloadControl(services)

    await payloads.focal_length_set(
        "RC123",
        m3_sub_type=1,
        payload_index="67-0-0",
        camera_type="zoom",
        zoom_factor=40,
    )
    await payloads.focal_length_set(
        "RC123",
        m3_sub_type=1,
        payload_index="67-0-0",
        camera_type="ir",
        zoom_factor=20,
    )

    with pytest.raises(DJIPayloadValidationError):
        await payloads.focal_length_set(
            "RC123",
            m3_sub_type=1,
            payload_index="67-0-0",
            camera_type="ir",
            zoom_factor=21,
        )

    assert [call[1] for call in services.calls] == [
        "camera_focal_length_set",
        "camera_focal_length_set",
    ]


@pytest.mark.asyncio
async def test_undocumented_m3m_cloud_payload_identity_fails_closed():
    services = FakeServices()
    payloads = DJIPayloadControl(services)

    with pytest.raises(DJIPayloadValidationError, match="unsupported M3 subtype"):
        await payloads.photo_take(
            "RC123",
            m3_sub_type=2,
            payload_index="68-0-0",
        )

    assert services.calls == []


@pytest.mark.asyncio
async def test_camera_exposure_and_focus_service_names_and_values():
    services = FakeServices()
    payloads = DJIPayloadControl(services)

    await payloads.exposure_value_set(
        "RC123",
        m3_sub_type=0,
        payload_index="66-0-0",
        camera_type="wide",
        exposure_value=16,
    )
    await payloads.exposure_mode_set(
        "RC123",
        m3_sub_type=0,
        payload_index="66-0-0",
        camera_type="wide",
        exposure_mode=4,
    )
    await payloads.focus_mode_set(
        "RC123",
        m3_sub_type=0,
        payload_index="66-0-0",
        camera_type="zoom",
        focus_mode=1,
    )
    await payloads.focus_value_set(
        "RC123",
        m3_sub_type=0,
        payload_index="66-0-0",
        camera_type="zoom",
        focus_value=42,
    )

    assert [call[1] for call in services.calls] == [
        "camera_exposure_set",
        "camera_exposure_mode_set",
        "camera_focus_mode_set",
        "camera_focus_value_set",
    ]
    assert services.calls[0][2]["exposure_value"] == 16
    assert services.calls[1][2]["exposure_mode"] == 4


@pytest.mark.asyncio
async def test_storage_targets_keep_ir_m3t_only():
    services = FakeServices()
    payloads = DJIPayloadControl(services)

    await payloads.photo_storage_set(
        "RC123",
        m3_sub_type=1,
        payload_index="67-0-0",
        settings=["current", "vision", "ir"],
    )

    with pytest.raises(DJIPayloadValidationError):
        await payloads.photo_storage_set(
            "RC123",
            m3_sub_type=0,
            payload_index="66-0-0",
            settings=["ir"],
        )


@pytest.mark.asyncio
async def test_frame_zoom_rejects_rectangle_outside_image():
    services = FakeServices()
    payloads = DJIPayloadControl(services)

    with pytest.raises(DJIPayloadValidationError, match="inside the camera frame"):
        await payloads.frame_zoom(
            "RC123",
            m3_sub_type=1,
            payload_index="67-0-0",
            camera_type="wide",
            locked=False,
            x=0.8,
            y=0.8,
            width=0.3,
            height=0.3,
        )


@pytest.mark.asyncio
async def test_screen_drag_preserves_dji_unbounded_finite_speeds():
    services = FakeServices()
    payloads = DJIPayloadControl(services)

    await payloads.screen_drag(
        "RC123",
        m3_sub_type=0,
        payload_index="66-0-0",
        locked=False,
        pitch_speed=1500.0,
        yaw_speed=-1500.0,
    )

    assert services.calls[0][2]["pitch_speed"] == 1500.0
    assert services.calls[0][2]["yaw_speed"] == -1500.0
