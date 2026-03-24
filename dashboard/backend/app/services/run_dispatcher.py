"""Bounded background runner for dashboard-triggered orchestrator cycles."""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor

from src.runtime import is_runtime_lock_held

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="DashboardCycle")
_active_future: Future[None] | None = None


def submit_cycle(*, dry_run: bool) -> bool:
    """Submit a manual cycle when no other cycle is already running."""
    global _active_future

    if _active_future is not None and not _active_future.done():
        return False

    if is_runtime_lock_held("orchestrator-cycle"):
        return False

    _active_future = _executor.submit(_run_cycle, dry_run)
    return True


def _run_cycle(dry_run: bool) -> None:
    from src.orchestrator.main import Orchestrator

    try:
        orch = Orchestrator(dry_run=dry_run)
        try:
            orch.run_cycle()
        finally:
            orch.close()
    except Exception as exc:
        logger.error("Triggered %s cycle failed: %s", "dry-run" if dry_run else "live", exc, exc_info=True)
