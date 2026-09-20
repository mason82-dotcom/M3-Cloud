from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings


engine: AsyncEngine = create_async_engine(
    settings.postgres_dsn,
    pool_pre_ping=True,
)
