"""Small Linux file-lock helpers for single-instance services."""

from __future__ import annotations

import json
import os
import socket
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import fcntl

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_RUNTIME_DIR = _PROJECT_ROOT / "data" / "runtime"
_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

DUPLICATE_INSTANCE_EXIT_CODE = 75


class RuntimeLockHeldError(RuntimeError):
    """Raised when an exclusive runtime lock is already held."""

    def __init__(self, *, lock_name: str, lock_path: Path, details: dict[str, Any] | None = None) -> None:
        self.lock_name = lock_name
        self.lock_path = lock_path
        self.details = details or {}
        owner_pid = self.details.get("pid")
        message = f"Runtime lock '{lock_name}' is already held"
        if owner_pid:
            message += f" by pid {owner_pid}"
        super().__init__(message)


@dataclass
class RuntimeLock:
    """Held advisory lock backed by a file descriptor."""

    name: str
    path: Path
    _handle: TextIO

    def release(self) -> None:
        """Release the lock and close the underlying file."""
        if self._handle.closed:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            if not self._handle.closed:
                self._handle.close()

    def __enter__(self) -> "RuntimeLock":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()


def _lock_path(lock_name: str) -> Path:
    return _RUNTIME_DIR / f"{lock_name}.lock"


def _write_metadata(handle: TextIO, metadata: dict[str, Any] | None) -> None:
    payload = {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "argv": sys.argv,
        "acquired_at": datetime.now(timezone.utc).isoformat(),
    }
    if metadata:
        payload["metadata"] = metadata

    handle.seek(0)
    handle.truncate()
    handle.write(json.dumps(payload, indent=2, sort_keys=True))
    handle.write("\n")
    handle.flush()


def _read_metadata(handle: TextIO) -> dict[str, Any] | None:
    try:
        handle.seek(0)
        raw = handle.read().strip()
        return json.loads(raw) if raw else None
    except Exception:
        return None


def acquire_runtime_lock(
    lock_name: str,
    *,
    metadata: dict[str, Any] | None = None,
    wait: bool = False,
) -> RuntimeLock:
    """Acquire an exclusive runtime lock or raise if it is already held."""
    path = _lock_path(lock_name)
    handle = path.open("a+", encoding="utf-8")
    flags = fcntl.LOCK_EX
    if not wait:
        flags |= fcntl.LOCK_NB

    try:
        fcntl.flock(handle.fileno(), flags)
    except BlockingIOError as exc:
        details = _read_metadata(handle)
        handle.close()
        raise RuntimeLockHeldError(lock_name=lock_name, lock_path=path, details=details) from exc

    _write_metadata(handle, metadata)
    return RuntimeLock(name=lock_name, path=path, _handle=handle)


def is_runtime_lock_held(lock_name: str) -> bool:
    """Return True when another process already holds the named runtime lock."""
    try:
        lock = acquire_runtime_lock(lock_name)
    except RuntimeLockHeldError:
        return True

    lock.release()
    return False
