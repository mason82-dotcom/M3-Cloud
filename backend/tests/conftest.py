import asyncio

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Keep asyncpg/SQLAlchemy integration tests on one event loop."""

    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
