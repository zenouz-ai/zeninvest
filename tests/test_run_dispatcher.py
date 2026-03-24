"""Tests for dashboard background cycle dispatching."""

from concurrent.futures import Future
from unittest.mock import MagicMock

from dashboard.backend.app.services import run_dispatcher


def test_submit_cycle_rejects_when_cycle_lock_held(monkeypatch) -> None:
    """Dashboard trigger should refuse to queue a new cycle when one is already active."""
    monkeypatch.setattr(run_dispatcher, "_active_future", None)
    monkeypatch.setattr(run_dispatcher, "is_runtime_lock_held", lambda _: True)

    assert run_dispatcher.submit_cycle(dry_run=True) is False


def test_submit_cycle_starts_background_job(monkeypatch) -> None:
    """Dashboard trigger should submit work when no cycle is active."""
    submitted_future: Future[None] = Future()
    fake_executor = MagicMock()
    fake_executor.submit.return_value = submitted_future

    monkeypatch.setattr(run_dispatcher, "_active_future", None)
    monkeypatch.setattr(run_dispatcher, "_executor", fake_executor)
    monkeypatch.setattr(run_dispatcher, "is_runtime_lock_held", lambda _: False)

    assert run_dispatcher.submit_cycle(dry_run=False) is True
    fake_executor.submit.assert_called_once()
