from fastapi import APIRouter, HTTPException, status

from app.dji.registry import DeviceRegistry
from app.dji.telemetry import TelemetryStore
from app.redis_client import redis_client


router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


@router.get("")
async def list_devices() -> list[dict[str, object]]:
    return await DeviceRegistry(redis_client).list_devices()


@router.get("/{sn}/telemetry")
async def device_telemetry(sn: str) -> dict[str, object]:
    telemetry = await TelemetryStore(redis_client).get(sn)
    if telemetry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No current telemetry for device",
        )
    return telemetry
