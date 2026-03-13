"""Research cache — dedupe by (ticker, tool, normalized_query), 4h TTL."""

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("research.cache")

# In-memory cache; key -> (results, expires_at)
_cache: dict[str, tuple[list[Any], datetime]] = {}
_CACHE_TTL_HOURS = 4


def _normalize_query(q: str) -> str:
    """Normalize query for cache key: lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def _cache_key(ticker: str, tool: str, query: str) -> str:
    nq = _normalize_query(query)
    raw = f"{ticker}|{tool}|{nq}"
    return hashlib.sha256(raw.encode()).hexdigest()


class ResearchCache:
    """Deduplicates research across committee members."""

    def __init__(self, ttl_hours: float | None = None) -> None:
        self._ttl_hours = ttl_hours or _CACHE_TTL_HOURS

    def get(self, ticker: str, tool: str, query: str) -> list[Any] | None:
        """Return cached results if valid."""
        key = _cache_key(ticker, tool, query)
        entry = _cache.get(key)
        if not entry:
            return None
        results, expires_at = entry
        if datetime.now(timezone.utc) >= expires_at:
            del _cache[key]
            return None
        return results

    def set(self, ticker: str, tool: str, query: str, results: list[Any]) -> None:
        """Store results with TTL."""
        key = _cache_key(ticker, tool, query)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=self._ttl_hours)
        _cache[key] = (results, expires_at)
