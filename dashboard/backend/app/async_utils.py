"""Helpers for running blocking work off the asyncio event loop."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


async def run_blocking(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run a synchronous callable in a worker thread."""
    return await asyncio.to_thread(func, *args, **kwargs)
