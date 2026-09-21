from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status

from app.api_devices import router as devices_router
from app.api_dji import router as dji_router
from app.api_dji_media import router as dji_media_router
from app.api_dji_waylines import router as dji_wayline_router
from app.api_dji_tsa import router as dji_tsa_router
from app.api_flights import router as flights_router
from app.api_media import router as media_router
from app.api_missions import router as missions_router
from app.api_processing import router as processing_router
from app.api_projects import router as projects_router
from app.config import settings
from app.database import session_factory
from app.dji.pilot_ws import DJIPilotWebSocketHub
from app.dji.service import DJIService
from app.flights.router import FlightTelemetryRouter
from app.flights.service import FlightRecorder
from app.health import readiness
from app.live import LiveTelemetryHub, router as live_router
from app.media.importer import MediaImporter
from app.media.watcher import MediaImportWatcher
from app.missions.uploader import MissionUploader, recover_interrupted_uploads
from app.processing.service import ProcessingManager
from app.api_operations import router as operations_router
from app.redis_client import redis_client
from app.storage import ensure_storage_buckets
from app.vehicles.mavlink import lyrebird_mavlink_collector
from app.vehicles.live import LyrebirdLiveBridge


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_storage_buckets()
    interrupted_uploads = await recover_interrupted_uploads(session_factory)
    app.state.recovered_mission_uploads = interrupted_uploads

    flight_recorder = FlightRecorder(session_factory)
    await flight_recorder.recover_interrupted()
    flight_router = FlightTelemetryRouter(flight_recorder)

    dji_service = DJIService.create(
        redis_client,
        telemetry_observer=flight_router,
    )
    live_hub = LiveTelemetryHub(
        redis_client,
        channel=settings.live_redis_channel,
    )
    dji_pilot_ws_hub = DJIPilotWebSocketHub(
        redis_client,
        channel=settings.live_redis_channel,
    )
    app.state.dji_service = dji_service
    app.state.flight_recorder = flight_recorder
    app.state.flight_router = flight_router
    app.state.live_hub = live_hub
    app.state.dji_pilot_ws_hub = dji_pilot_ws_hub
    lyrebird_live = LyrebirdLiveBridge(
        redis_client,
        lyrebird_mavlink_collector,
        telemetry_observer=flight_router,
    )
    app.state.lyrebird_live = lyrebird_live
    app.state.lyrebird_mavlink_collector = lyrebird_mavlink_collector
    app.state.mission_uploader = MissionUploader(lyrebird_mavlink_collector)

    processing_manager = ProcessingManager(
        session_factory,
        media_root=settings.media_import_root,
        media_handoff_root=settings.media_import_handoff_root,
        external_result_root=settings.processing_import_root,
        external_result_handoff_root=settings.processing_import_handoff_root,
        webodm_enabled=settings.webodm_enabled,
        webodm_url=settings.webodm_url,
        webodm_token=settings.webodm_token,
        webodm_username=settings.webodm_username,
        webodm_password=settings.webodm_password,
        webodm_timeout_seconds=settings.webodm_timeout_seconds,
        poll_interval_seconds=settings.processing_poll_interval_seconds,
    )
    app.state.processing_manager = processing_manager

    media_importer = None
    media_watcher = None
    if settings.media_import_enabled:
        media_importer = MediaImporter(
            session_factory,
            root=settings.media_import_root,
            min_age_seconds=settings.media_import_min_age_seconds,
            filename_timezone=settings.media_filename_timezone,
            auto_match_flights=settings.media_auto_match_flights,
            auto_match_margin_seconds=settings.media_auto_match_margin_seconds,
            auto_match_max_distance_m=settings.media_auto_match_max_distance_m,
            auto_match_min_gps_fraction=settings.media_auto_match_min_gps_fraction,
            auto_match_max_gps_samples=settings.media_auto_match_max_gps_samples,
            auto_match_max_sample_time_delta_seconds=settings.media_auto_match_max_sample_time_delta_seconds,
        )
        media_watcher = MediaImportWatcher(
            media_importer,
            interval_seconds=settings.media_import_scan_interval_seconds,
        )
        app.state.media_importer = media_importer
        app.state.media_import_watcher = media_watcher

    await live_hub.start()
    await dji_pilot_ws_hub.start()
    await processing_manager.start()
    await lyrebird_mavlink_collector.start()
    await lyrebird_live.start()
    if media_watcher is not None:
        await media_watcher.start()

    if settings.dji_mqtt_enabled:
        await dji_service.transport.start()

    try:
        yield
    finally:
        if settings.dji_mqtt_enabled:
            await dji_service.transport.stop()
        if media_watcher is not None:
            await media_watcher.stop()
        await processing_manager.stop()
        await lyrebird_live.stop()
        await lyrebird_mavlink_collector.stop()
        await dji_pilot_ws_hub.stop()
        await live_hub.stop()


app = FastAPI(
    title="M3-Cloud",
    version="0.2.0",
    lifespan=lifespan,
)
app.include_router(devices_router)
app.include_router(dji_router)
app.include_router(dji_media_router)
app.include_router(dji_wayline_router)
app.include_router(dji_tsa_router)
app.include_router(flights_router)
app.include_router(media_router)
app.include_router(missions_router)
app.include_router(processing_router)
app.include_router(projects_router)
app.include_router(live_router)
app.include_router(operations_router)


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
