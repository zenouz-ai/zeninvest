"""Deterministic fingerprints for cycle context and attribution."""

from __future__ import annotations

import hashlib
import json
import subprocess  # nosec B404
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def stable_hash(payload: Any) -> str:
    """Return a deterministic short hash for a JSON-serializable payload."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def get_repo_sha() -> str:
    """Return the current git HEAD SHA, or 'unknown' when unavailable."""
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            check=True,
            text=True,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"

