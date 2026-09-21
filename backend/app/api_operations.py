from fastapi import APIRouter, Request

from app.vehicles.dji_cloud import DJICloudVehicleProvider
from app.vehicles.lyrebird import LyrebirdVehicleProvider
from app.vehicles.registry import VehicleRegistry
from app.redis_client import redis_client
from app.config import settings


router = APIRouter(prefix="/api/v1", tags=["operations"])


def _registry(request: Request | None = None) -> VehicleRegistry:
    collector = getattr(getattr(request, "app", None), "state", None)
    mavlink = (
        getattr(collector, "lyrebird_mavlink_collector", None)
        if collector is not None
        else None
    )
    return VehicleRegistry(
        [
            DJICloudVehicleProvider(redis_client),
            LyrebirdVehicleProvider(mavlink_collector=mavlink),
        ]
    )


def _dji_health(dji_service: object | None) -> dict[str, object]:
    if not settings.dji_mqtt_enabled:
        return {
            "ok": False,
            "status": "disabled",
            "connected": False,
        }

    transport = getattr(dji_service, "transport", None)
    connected = bool(getattr(transport, "connected", False))
    result: dict[str, object] = {
        "ok": connected,
        "status": "connected" if connected else "disconnected",
        "connected": connected,
    }
    reason = getattr(transport, "last_connection_reason", None)
    if reason:
        result["last_reason"] = str(reason)
    return result


@router.get("/vehicles")
async def list_vehicles(request: Request) -> list[dict[str, object]]:
    return [
        vehicle.as_dict()
        for vehicle in await _registry(request).list_vehicles()
    ]


@router.get("/system/health")
async def system_health(request: Request) -> dict[str, object]:
    from app.health import readiness

    ready = await readiness()
    dji_service = getattr(request.app.state, "dji_service", None)
    return {
        "ok": ready["ok"],
        "components": {
            "postgres": ready["services"]["postgres"],
            "redis": ready["services"]["redis"],
            "storage": ready["services"]["object_storage"],
            "mqtt": ready["services"]["emqx"],
            "dji": _dji_health(dji_service),
            "lyrebird": (
                getattr(request.app.state, "lyrebird_live", None).health()
                if settings.lyrebird_enabled
                and getattr(request.app.state, "lyrebird_live", None) is not None
                else {"ok": False, "status": "disabled", "hosts": {}}
            ),
        },
    }
