from __future__ import annotations

from typing import Any, Iterable

from app.dji.models.payload import (
    DJIPayloadValidationError,
    bounded_number,
    normalized_storage_settings,
    require_m3t,
    strict_int,
    validate_camera_type,
    validate_payload_index,
    validate_unit_point,
    validate_unit_rect,
)
from app.dji.services import DJIServiceClient, DJIServiceResponse


class DJIPayloadControl:
    """DJI Pilot-to-Cloud payload-control services for the Mavic 3 Enterprise family."""

    def __init__(self, services: DJIServiceClient) -> None:
        self.services = services

    @staticmethod
    def _payload(
        m3_sub_type: int,
        payload_index: str,
    ) -> dict[str, Any]:
        return {
            "payload_index": validate_payload_index(
                m3_sub_type,
                payload_index,
            )
        }

    @staticmethod
    def _camera(
        m3_sub_type: int,
        payload_index: str,
        camera_type: str,
    ) -> dict[str, Any]:
        data = DJIPayloadControl._payload(m3_sub_type, payload_index)
        data["camera_type"] = validate_camera_type(
            m3_sub_type,
            camera_type,
        )
        return data

    async def camera_mode_switch(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        camera_mode: int,
    ) -> DJIServiceResponse:
        mode = strict_int(camera_mode, name="camera_mode")
        if mode not in (0, 1, 2, 3):
            raise DJIPayloadValidationError(
                "camera_mode must be between 0 and 3"
            )
        data = self._payload(m3_sub_type, payload_index)
        data["camera_mode"] = mode
        return await self.services.call(
            gateway_sn,
            "camera_mode_switch",
            data,
        )

    async def recording_start(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
    ) -> DJIServiceResponse:
        return await self.services.call(
            gateway_sn,
            "camera_recording_start",
            self._payload(m3_sub_type, payload_index),
        )

    async def recording_stop(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
    ) -> DJIServiceResponse:
        return await self.services.call(
            gateway_sn,
            "camera_recording_stop",
            self._payload(m3_sub_type, payload_index),
        )

    async def screen_drag(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        locked: bool,
        pitch_speed: float,
        yaw_speed: float,
    ) -> DJIServiceResponse:
        if not isinstance(locked, bool):
            raise DJIPayloadValidationError("locked must be boolean")
        data = self._payload(m3_sub_type, payload_index)
        data.update(
            {
                "locked": locked,
                "pitch_speed": bounded_number(
                    pitch_speed,
                    name="pitch_speed",
                    minimum=-1000.0,
                    maximum=1000.0,
                ),
                "yaw_speed": bounded_number(
                    yaw_speed,
                    name="yaw_speed",
                    minimum=-1000.0,
                    maximum=1000.0,
                ),
            }
        )
        return await self.services.call(
            gateway_sn,
            "camera_screen_drag",
            data,
        )

    async def aim(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        camera_type: str,
        locked: bool,
        x: float,
        y: float,
    ) -> DJIServiceResponse:
        if not isinstance(locked, bool):
            raise DJIPayloadValidationError("locked must be boolean")
        px, py = validate_unit_point(x, y)
        data = self._camera(m3_sub_type, payload_index, camera_type)
        data.update({"locked": locked, "x": px, "y": py})
        return await self.services.call(gateway_sn, "camera_aim", data)

    async def focal_length_set(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        camera_type: str,
        zoom_factor: float,
    ) -> DJIServiceResponse:
        camera = validate_camera_type(m3_sub_type, camera_type)
        maximum = 20.0 if camera == "ir" else 200.0
        zoom = bounded_number(
            zoom_factor,
            name="zoom_factor",
            minimum=2.0,
            maximum=maximum,
        )
        data = self._payload(m3_sub_type, payload_index)
        data.update(
            {
                "camera_type": camera,
                "zoom_factor": zoom,
            }
        )
        return await self.services.call(
            gateway_sn,
            "camera_focal_length_set",
            data,
        )

    async def gimbal_reset(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        reset_mode: int,
    ) -> DJIServiceResponse:
        mode = strict_int(reset_mode, name="reset_mode")
        if mode not in (0, 1, 2, 3):
            raise DJIPayloadValidationError(
                "reset_mode must be between 0 and 3"
            )
        data = self._payload(m3_sub_type, payload_index)
        data["reset_mode"] = mode
        return await self.services.call(gateway_sn, "gimbal_reset", data)

    async def look_at(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        locked: bool,
        latitude: float,
        longitude: float,
        height: float,
    ) -> DJIServiceResponse:
        if not isinstance(locked, bool):
            raise DJIPayloadValidationError("locked must be boolean")
        data = self._payload(m3_sub_type, payload_index)
        data.update(
            {
                "locked": locked,
                "latitude": bounded_number(
                    latitude,
                    name="latitude",
                    minimum=-90.0,
                    maximum=90.0,
                ),
                "longitude": bounded_number(
                    longitude,
                    name="longitude",
                    minimum=-180.0,
                    maximum=180.0,
                ),
                "height": bounded_number(
                    height,
                    name="height",
                    minimum=2.0,
                    maximum=10000.0,
                ),
            }
        )
        return await self.services.call(gateway_sn, "camera_look_at", data)

    async def screen_split(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        enable: bool,
    ) -> DJIServiceResponse:
        require_m3t(m3_sub_type, "screen_split")
        if not isinstance(enable, bool):
            raise DJIPayloadValidationError("enable must be boolean")
        data = self._payload(m3_sub_type, payload_index)
        data["enable"] = enable
        return await self.services.call(
            gateway_sn,
            "camera_screen_split",
            data,
        )

    async def photo_storage_set(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        settings: Iterable[str],
    ) -> DJIServiceResponse:
        data = self._payload(m3_sub_type, payload_index)
        data["photo_storage_settings"] = normalized_storage_settings(
            m3_sub_type,
            settings,
        )
        return await self.services.call(
            gateway_sn,
            "photo_storage_set",
            data,
        )

    async def video_storage_set(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        settings: Iterable[str],
    ) -> DJIServiceResponse:
        data = self._payload(m3_sub_type, payload_index)
        data["video_storage_settings"] = normalized_storage_settings(
            m3_sub_type,
            settings,
        )
        return await self.services.call(
            gateway_sn,
            "video_storage_set",
            data,
        )

    async def frame_zoom(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        camera_type: str,
        locked: bool,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> DJIServiceResponse:
        if not isinstance(locked, bool):
            raise DJIPayloadValidationError("locked must be boolean")
        left, top, w, h = validate_unit_rect(x, y, width, height)
        data = self._camera(m3_sub_type, payload_index, camera_type)
        data.update(
            {
                "locked": locked,
                "x": left,
                "y": top,
                "width": w,
                "height": h,
            }
        )
        return await self.services.call(
            gateway_sn,
            "camera_frame_zoom",
            data,
        )

    async def ir_metering_area_set(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> DJIServiceResponse:
        require_m3t(m3_sub_type, "ir_metering_area_set")
        left, top, w, h = validate_unit_rect(x, y, width, height)
        data = self._payload(m3_sub_type, payload_index)
        data.update(
            {
                "x": left,
                "y": top,
                "width": w,
                "height": h,
            }
        )
        return await self.services.call(
            gateway_sn,
            "ir_metering_area_set",
            data,
        )

    async def ir_metering_point_set(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        x: float,
        y: float,
    ) -> DJIServiceResponse:
        require_m3t(m3_sub_type, "ir_metering_point_set")
        px, py = validate_unit_point(x, y)
        data = self._payload(m3_sub_type, payload_index)
        data.update({"x": px, "y": py})
        return await self.services.call(
            gateway_sn,
            "ir_metering_point_set",
            data,
        )

    async def ir_metering_mode_set(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        mode: int,
    ) -> DJIServiceResponse:
        require_m3t(m3_sub_type, "ir_metering_mode_set")
        value = strict_int(mode, name="mode")
        if value not in (0, 1, 2):
            raise DJIPayloadValidationError(
                "infrared metering mode must be 0, 1 or 2"
            )
        data = self._payload(m3_sub_type, payload_index)
        data["mode"] = value
        return await self.services.call(
            gateway_sn,
            "ir_metering_mode_set",
            data,
        )

    async def point_focus(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        camera_type: str,
        x: float,
        y: float,
    ) -> DJIServiceResponse:
        px, py = validate_unit_point(x, y)
        data = self._camera(m3_sub_type, payload_index, camera_type)
        if data["camera_type"] == "ir":
            raise DJIPayloadValidationError(
                "point focus is not valid for the infrared camera"
            )
        data.update({"x": px, "y": py})
        return await self.services.call(
            gateway_sn,
            "camera_point_focus_action",
            data,
        )

    async def focus_value_set(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        camera_type: str,
        focus_value: int,
    ) -> DJIServiceResponse:
        data = self._camera(m3_sub_type, payload_index, camera_type)
        if data["camera_type"] == "ir":
            raise DJIPayloadValidationError(
                "focus value is not valid for the infrared camera"
            )
        value = strict_int(focus_value, name="focus_value")
        if value < 0:
            raise DJIPayloadValidationError(
                "focus_value must be non-negative"
            )
        data["focus_value"] = value
        return await self.services.call(
            gateway_sn,
            "camera_focus_value_set",
            data,
        )

    async def focus_mode_set(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        camera_type: str,
        focus_mode: int,
    ) -> DJIServiceResponse:
        data = self._camera(m3_sub_type, payload_index, camera_type)
        if data["camera_type"] == "ir":
            raise DJIPayloadValidationError(
                "focus mode is not valid for the infrared camera"
            )
        mode = strict_int(focus_mode, name="focus_mode")
        if mode not in (0, 1, 2):
            raise DJIPayloadValidationError(
                "focus_mode must be 0, 1 or 2"
            )
        data["focus_mode"] = mode
        return await self.services.call(
            gateway_sn,
            "camera_focus_mode_set",
            data,
        )

    async def exposure_value_set(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        camera_type: str,
        exposure_value: int,
    ) -> DJIServiceResponse:
        data = self._camera(m3_sub_type, payload_index, camera_type)
        if data["camera_type"] == "ir":
            raise DJIPayloadValidationError(
                "exposure value is not valid for the infrared camera"
            )
        value = strict_int(exposure_value, name="exposure_value")
        if value not in {*range(1, 32), 255}:
            raise DJIPayloadValidationError(
                "exposure_value must be 1..31 or 255"
            )
        data["exposure_value"] = value
        return await self.services.call(
            gateway_sn,
            "camera_exposure_set",
            data,
        )

    async def exposure_mode_set(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
        camera_type: str,
        exposure_mode: int,
    ) -> DJIServiceResponse:
        data = self._camera(m3_sub_type, payload_index, camera_type)
        if data["camera_type"] == "ir":
            raise DJIPayloadValidationError(
                "exposure mode is not valid for the infrared camera"
            )
        mode = strict_int(exposure_mode, name="exposure_mode")
        if mode not in (1, 2, 3, 4):
            raise DJIPayloadValidationError(
                "exposure_mode must be between 1 and 4"
            )
        data["exposure_mode"] = mode
        return await self.services.call(
            gateway_sn,
            "camera_exposure_mode_set",
            data,
        )

    async def photo_stop(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
    ) -> DJIServiceResponse:
        return await self.services.call(
            gateway_sn,
            "camera_photo_stop",
            self._payload(m3_sub_type, payload_index),
        )

    async def photo_take(
        self,
        gateway_sn: str,
        *,
        m3_sub_type: int,
        payload_index: str,
    ) -> DJIServiceResponse:
        return await self.services.call(
            gateway_sn,
            "camera_photo_take",
            self._payload(m3_sub_type, payload_index),
        )
