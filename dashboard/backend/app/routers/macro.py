"""Macro / World News router — MacroState, MacroSignalLog, MacroHeadline."""

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, func

from src.data.database import get_session
from src.data.models import MacroHeadline, MacroSignalLog, MacroState
from src.utils.config import get_settings

from ..schemas import (
    MacroHeadlineSchema,
    MacroSignalSchema,
    MacroStateSchema,
    MacroSummarySchema,
)

router = APIRouter()
settings = get_settings()


def _parse_macro_state(row: MacroState) -> dict:
    """Convert a MacroState ORM row to a dict matching MacroStateSchema."""
    return {
        "id": row.id,
        "timestamp": row.timestamp,
        "regime": row.regime,
        "confidence_score": row.confidence_score,
        "source": row.source,
        "top_signals": json.loads(row.top_signals_json or "[]"),
        "action_plan": json.loads(row.action_plan_json or "{}"),
        "sector_summary": row.sector_summary,
        "economic_highlights": row.economic_highlights,
    }


@router.get("/state", response_model=MacroStateSchema | None)
async def get_latest_state():
    """Latest proactive macro state snapshot."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        row = session.query(MacroState).order_by(desc(MacroState.timestamp)).first()
        if row is None:
            return None
        return _parse_macro_state(row)
    finally:
        session.close()


@router.get("/state/history", response_model=list[MacroStateSchema])
async def get_state_history(
    days: int = Query(default=7, ge=1, le=90),
):
    """Macro state history for the past N days (regime timeline)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    session = get_session()
    try:
        rows = (
            session.query(MacroState)
            .filter(MacroState.timestamp >= cutoff)
            .order_by(desc(MacroState.timestamp))
            .all()
        )
        return [_parse_macro_state(r) for r in rows]
    finally:
        session.close()


@router.get("/headlines", response_model=list[MacroHeadlineSchema])
async def get_headlines(
    days: int = Query(default=7, ge=1, le=90),
    category: str = Query(default="all"),
    limit: int = Query(default=200, ge=1, le=500),
):
    """Archived macro headlines for the past N days, optionally filtered by category."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    session = get_session()
    try:
        query = session.query(MacroHeadline).filter(MacroHeadline.published_at >= cutoff)
        if category and category != "all":
            query = query.filter(MacroHeadline.category == category)
        rows = query.order_by(desc(MacroHeadline.published_at)).limit(limit).all()
        return rows
    finally:
        session.close()


@router.get("/signals", response_model=list[MacroSignalSchema])
async def get_signals(
    days: int = Query(default=7, ge=1, le=90),
):
    """Macro signal audit trail for the past N days."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    session = get_session()
    try:
        rows = (
            session.query(MacroSignalLog)
            .filter(MacroSignalLog.timestamp >= cutoff)
            .order_by(desc(MacroSignalLog.timestamp))
            .all()
        )
        return rows
    finally:
        session.close()


@router.get("/summary", response_model=MacroSummarySchema)
async def get_macro_summary():
    """Compact macro summary for the Dashboard Home card."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
    session = get_session()
    try:
        # Latest macro state
        latest = session.query(MacroState).order_by(desc(MacroState.timestamp)).first()

        # Headline counts by category (past 7 days)
        cat_counts_raw = (
            session.query(MacroHeadline.category, func.count(MacroHeadline.id))
            .filter(MacroHeadline.published_at >= cutoff_7d)
            .group_by(MacroHeadline.category)
            .all()
        )
        category_counts = {cat or "general": cnt for cat, cnt in cat_counts_raw}
        total_headlines = sum(category_counts.values())

        top_signal = None
        if latest:
            signals = json.loads(latest.top_signals_json or "[]")
            if signals:
                top_signal = signals[0].get("signal_text")

        return MacroSummarySchema(
            regime=latest.regime if latest else None,
            confidence_score=latest.confidence_score if latest else None,
            top_signal=top_signal,
            headline_count_7d=total_headlines,
            category_counts=category_counts,
            last_updated=latest.timestamp.isoformat() if latest else None,
        )
    finally:
        session.close()
