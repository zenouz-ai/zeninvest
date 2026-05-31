"""Authenticated routes for memory / similar-case retrieval (US-6.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.learning.memory.neo4j_sync import query_similar_sector_regime
from src.learning.memory.retrieval import find_similar_cases
from src.utils.config import get_settings

router = APIRouter()
settings = get_settings()


def _ensure_dashboard_enabled() -> None:
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")


@router.get("/similar")
async def similar_cases(
    q: str = Query(..., min_length=3),
    ticker: str | None = Query(default=None),
    regime: str | None = Query(default=None),
    k: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    """Vector similarity search over exported decision narratives."""
    _ensure_dashboard_enabled()
    hits = find_similar_cases(
        thesis_text=q,
        ticker=ticker,
        regime=regime,
        as_of_ts=datetime.now(),
        k=k,
    )
    return {"query": q, "hits": hits, "count": len(hits)}


@router.get("/graph/sector-regime")
async def graph_sector_regime(
    sector: str = Query(...),
    regime: str = Query(...),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    """Read-only Neo4j query: decisions in sector during macro regime."""
    _ensure_dashboard_enabled()
    rows = query_similar_sector_regime(sector, regime, limit=limit)
    return {"sector": sector, "regime": regime, "decisions": rows, "count": len(rows)}
