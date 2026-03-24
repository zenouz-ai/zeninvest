"""Tests for production runtime locking helpers."""

from pathlib import Path

import pytest

from src.runtime import locking


def test_acquire_runtime_lock_rejects_duplicate_holder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A second non-blocking acquire should fail while the first lock is held."""
    monkeypatch.setattr(locking, "_RUNTIME_DIR", tmp_path)

    first = locking.acquire_runtime_lock("scheduler", metadata={"service": "scheduler"})
    try:
        with pytest.raises(locking.RuntimeLockHeldError) as exc_info:
            locking.acquire_runtime_lock("scheduler")

        assert exc_info.value.details["metadata"]["service"] == "scheduler"
        assert exc_info.value.lock_path == tmp_path / "scheduler.lock"
    finally:
        first.release()


def test_is_runtime_lock_held_reflects_lock_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lock probe should return True only while another holder owns the lock."""
    monkeypatch.setattr(locking, "_RUNTIME_DIR", tmp_path)

    assert locking.is_runtime_lock_held("api") is False

    held = locking.acquire_runtime_lock("api")
    try:
        assert locking.is_runtime_lock_held("api") is True
    finally:
        held.release()

    assert locking.is_runtime_lock_held("api") is False
