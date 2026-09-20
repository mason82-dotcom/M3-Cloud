from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status

from app.api_devices import router as devices_router
from app.api_flights import router as flights_router
from app.config import settings
from app.database import session_factory
from app.dji.service import DJIService
from app.flights.service import FlightRecorder
from app.health import readiness
from app.live import LiveTelemetryHub, router as live_router
from app.redis_client import redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    flight_recorder = FlightRecorder(session_factory)
    await flight_recorder.recover_interrupted()

    dji_service = DJIService.create(
        redis_client,
        telemetry_observer=flight_recorder,
    )
    live_hub = LiveTelemetryHub(
        redis_client,
        channel=settings.live_redis_channel,
    )
    app.state.dji_service = dji_service
    app.state.flight_recorder = flight_recorder
    app.state.live_hub = live_hub

    await live_hub.start()

    if settings.dji_mqtt_enabled:
        await dji_service.transport.start()

    try:
        yield
    finally:
        if settings.dji_mqtt_enabled:
            await dji_service.transport.stop()
        await live_hub.stop()


app = FastAPI(
    title="M3-Cloud",
    version="0.2.0",
    lifespan=lifespan,
)
app.include_router(devices_router)
app.include_router(flights_router)
app.include_router(live_router)


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
