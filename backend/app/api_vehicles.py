from fastapi import APIRouter

from app.vehicles.lyrebird import LyrebirdVehicleProvider
from app.vehicles.mavlink import lyrebird_mavlink_collector

router = APIRouter(prefix="/api/v1/vehicles", tags=["vehicles"])

@router.get("")
async def list_vehicles() -> list[dict[str, object]]:
    provider = LyrebirdVehicleProvider(mavlink_collector=lyrebird_mavlink_collector)
    return [vehicle.as_dict() for vehicle in await provider.list_vehicles()]
