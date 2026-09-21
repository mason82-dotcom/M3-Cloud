from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.dji.services import DJIServiceClient


VideoType = Literal["normal", "thermal", "wide", "zoom"]


@dataclass(frozen=True)
class LiveStartRequest:
    video_id: str
    url_type: int
    url: str
    video_quality: int


class DJILiveView:
    """Pilot-to-Cloud live streaming commands for RC Pro Enterprise."""

    def __init__(self, services: DJIServiceClient):
        self.services = services

    async def start(
        self,
        gateway_sn: str,
        *,
        video_id: str,
        url_type: int,
        url: str,
        video_quality: int,
    ) -> dict[str, Any]:
        response = await self.services.call(
            gateway_sn,
            "live_start_push",
            {
                "video_id": video_id,
                "url_type": int(url_type),
                "url": url,
                "video_quality": int(video_quality),
            },
        )
        return self._response(response)

    async def stop(self, gateway_sn: str, *, video_id: str) -> dict[str, Any]:
        response = await self.services.call(
            gateway_sn,
            "live_stop_push",
            {"video_id": video_id},
        )
        return self._response(response)

    async def set_quality(
        self,
        gateway_sn: str,
        *,
        video_id: str,
        video_quality: int,
    ) -> dict[str, Any]:
        response = await self.services.call(
            gateway_sn,
            "live_set_quality",
            {
                "video_id": video_id,
                "video_quality": int(video_quality),
            },
        )
        return self._response(response)

    async def set_lens(
        self,
        gateway_sn: str,
        *,
        video_id: str,
        video_type: VideoType,
    ) -> dict[str, Any]:
        response = await self.services.call(
            gateway_sn,
            "live_lens_change",
            {
                "video_id": video_id,
                "video_type": video_type,
            },
        )
        return self._response(response)

    @staticmethod
    def _response(response) -> dict[str, Any]:
        return {
            "gateway_sn": response.gateway_sn,
            "method": response.method,
            "tid": response.tid,
            "bid": response.bid,
            "result": response.result,
            "output": response.output,
        }
