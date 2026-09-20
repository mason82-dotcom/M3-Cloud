from fastapi import APIRouter

from app.redis_client import redis_client
from app.dji.registry import DeviceRegistry


router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


@router.get("")
async def list_devices() -> list[dict[str, object]]:
    return await DeviceRegistry(redis_client).list_devices()
