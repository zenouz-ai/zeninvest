"""Pytest configuration. Sets test database before any imports."""
import asyncio
import os

import pytest

# Use in-memory SQLite for all tests so they never touch production data.
# Must run before src.data.database (or any module that imports it) is loaded.
os.environ["INVESTMENT_AGENT_USE_INMEMORY_DB"] = "1"


@pytest.fixture(scope="session", autouse=True)
def _session_event_loop():
    """Provide a default event loop for legacy sync-style async tests on Python 3.14+."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield loop
    finally:
        loop.close()
