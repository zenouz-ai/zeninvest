"""Research cache — dedupe by (ticker, tool, normalized_query), 4h TTL.

Durable (US-9.4): results are persisted in SQLite (``research_cache`` table) so
they survive process restarts and dedupe across cycles. The public API
(``get``/``set``) is unchanged, so ``ResearchExecutor`` needs no edits.
"""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from src.data.database import get_session
from src.data.models import ResearchCache as ResearchCacheRow
from src.utils.logger import get_logger

logger = get_logger("research.cache")

_CACHE_TTL_HOURS = 4


def _normalize_query(q: str) -> str:
    """Normalize query for cache key: lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def _cache_key(ticker: str, tool: str, query: str) -> str:
    nq = _normalize_query(query)
    raw = f"{ticker}|{tool}|{nq}"
    return hashlib.sha256(raw.encode()).hexdigest()


class ResearchCache:
    """Deduplicates research across committee members (SQLite-backed)."""

    def __init__(self, ttl_hours: float | None = None) -> None:
        self._ttl_hours = ttl_hours or _CACHE_TTL_HOURS

    def get(self, ticker: str, tool: str, query: str) -> list[Any] | None:
        """Return cached results if a non-expired row exists."""
        key = _cache_key(ticker, tool, query)
        session = get_session()
        try:
            row = (
                session.query(ResearchCacheRow)
                .filter(
                    ResearchCacheRow.cache_key == key,
                    ResearchCacheRow.expires_at > datetime.now(timezone.utc),
                )
                .first()
            )
            if row is None:
                return None
            results: list[Any] = json.loads(str(row.results_json))
            return results
        except Exception as exc:  # cache must never break research
            logger.debug(f"research cache get failed: {exc}")
            session.rollback()
            return None
        finally:
            session.close()

    def set(self, ticker: str, tool: str, query: str, results: list[Any]) -> None:
        """Store results with TTL (upsert by cache_key)."""
        key = _cache_key(ticker, tool, query)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=self._ttl_hours)
        session = get_session()
        try:
            session.query(ResearchCacheRow).filter(
                ResearchCacheRow.cache_key == key
            ).delete()
            session.add(
                ResearchCacheRow(
                    cache_key=key,
                    ticker=(ticker or "")[:50],
                    tool=(tool or "")[:50],
                    results_json=json.dumps(results, default=str),
                    expires_at=expires_at,
                )
            )
            session.commit()
        except Exception as exc:
            logger.debug(f"research cache set failed: {exc}")
            session.rollback()
        finally:
            session.close()
