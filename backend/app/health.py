import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.redis_client import redis_client
from app.storage import create_storage_client


async def _check(name: str, probe: Callable[[], Awaitable[Any]]) -> tuple[str, dict[str, Any]]:
    try:
        await probe()
    except Exception as exc:  # Health endpoints must report failures, not crash the API.
        return name, {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return name, {"ok": True}


async def _database_probe() -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def _redis_probe() -> None:
    await redis_client.ping()


async def _object_storage_probe() -> None:
    client = create_storage_client()
    await asyncio.to_thread(client.list_buckets)


async def _emqx_probe() -> None:
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(settings.emqx_host, settings.emqx_port),
        timeout=3,
    )
    del reader
    writer.close()
    await writer.wait_closed()


async def readiness() -> dict[str, Any]:
    checks = await asyncio.gather(
        _check("postgres", _database_probe),
        _check("redis", _redis_probe),
        _check("object_storage", _object_storage_probe),
        _check("emqx", _emqx_probe),
    )
    services = dict(checks)
    return {
        "ok": all(service["ok"] for service in services.values()),
        "services": services,
    }
