from fastapi import FastAPI, Response, status

from app.config import settings
from app.health import readiness


app = FastAPI(
    title="M3-Cloud",
    version="0.1.0",
)


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
