"""Tests for dashboard async utilities."""

import asyncio

from dashboard.backend.app.async_utils import run_blocking


def test_run_blocking_executes_sync_function():
    def add(a: int, b: int) -> int:
        return a + b

    result = asyncio.run(run_blocking(add, 2, 3))
    assert result == 5
