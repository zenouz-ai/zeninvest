"""High-level retrieval API for similar past decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.learning.memory.vector_store import search_similar
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("learning.memory.retrieval")


def find_similar_cases(
    *,
    thesis_text: str,
    ticker: str | None = None,
    regime: str | None = None,
    as_of_ts: datetime | None = None,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Find similar historical cases (shadow-only evidence retrieval)."""
    settings = get_settings()
    if not settings.learning_embeddings_enabled:
        logger.debug("Embeddings disabled; returning empty similar-case set")
        return []

    query = thesis_text
    if regime:
        query = f"Macro regime: {regime}\n\n{query}"

    as_of = as_of_ts.isoformat() if as_of_ts else None
    try:
        hits = search_similar(query, as_of_ts=as_of, ticker=ticker, k=k)
    except Exception as exc:
        logger.warning("Similar-case search failed: %s", exc)
        return []
    return hits
