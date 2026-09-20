from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status

from app.api_devices import router as devices_router
from app.config import settings
from app.dji.service import DJIService
from app.health import readiness
from app.redis_client import redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    dji_service = DJIService.create(redis_client)
    app.state.dji_service = dji_service

    if settings.dji_mqtt_enabled:
        await dji_service.transport.start()

    try:
        yield
    finally:
        if settings.dji_mqtt_enabled:
            await dji_service.transport.stop()


app = FastAPI(
    title="M3-Cloud",
    version="0.2.0",
    lifespan=lifespan,
)
app.include_router(devices_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "m3-cloud",
        "environment": settings.environment,
    }


@app.get("/health/live")
async def health_live() -> dict[str, object]:
    return {
        "ok": True,
        "service": "m3-cloud",
    }


@app.get("/health/ready")
async def health_ready(response: Response) -> dict[str, object]:
    result = await readiness()
    if not result["ok"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
