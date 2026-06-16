"""Outcomes router — trade_outcomes and aggregate stats."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, func

from src.agents.reporting.realized_trades import realized_trade_outcomes_query
from src.agents.reporting.trade_review import build_trade_timeline
from src.data.database import get_session
from src.data.models import TradeOutcome
from src.utils.config import get_settings

from ..schemas import NorthStarMetricsSchema, OutcomesStatsSchema, TradeOutcomeSchema, TradeTimelineSchema

router = APIRouter()
settings = get_settings()


@router.get("/", response_model=list[TradeOutcomeSchema])
async def list_outcomes(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ticker: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
):
    """Closed trade outcomes, paginated."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        query = realized_trade_outcomes_query(session)
        if ticker:
            query = query.filter(TradeOutcome.ticker == ticker)
        if start_date:
            query = query.filter(TradeOutcome.sell_timestamp >= start_date)
        if end_date:
            query = query.filter(TradeOutcome.sell_timestamp <= end_date)
        rows = query.order_by(desc(TradeOutcome.sell_timestamp)).offset(offset).limit(limit).all()
        return rows
    finally:
        session.close()


@router.get("/north-star", response_model=NorthStarMetricsSchema)
async def get_north_star_metrics(
    window_days: int = Query(default=90, ge=7, le=365),
):
    """Rolling north-star KPIs (pace-aligned v6 labels on closed trades)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    from src.agents.reporting.north_star_metrics import compute_north_star_metrics

    session = get_session()
    try:
        rows = realized_trade_outcomes_query(session).all()
        metrics = compute_north_star_metrics(rows, window_days=window_days)
        return metrics.to_dict()
    finally:
        session.close()


@router.get("/stats", response_model=OutcomesStatsSchema)
async def get_outcomes_stats():
    """Aggregate stats: win rate, avg P&L, avg holding period, best/worst."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        base = realized_trade_outcomes_query(session)
        total = base.count()
        if total == 0:
            return OutcomesStatsSchema(
                total_trades=0,
                win_rate_pct=0.0,
                avg_pnl_pct=0.0,
                avg_holding_days=0.0,
                best_trade_pct=None,
                worst_trade_pct=None,
            )
        wins = base.filter(TradeOutcome.pnl_gbp > 0).count()
        win_rate = (wins / total * 100.0) if total else 0.0
        avg_pnl = base.with_entities(func.avg(TradeOutcome.pnl_pct)).scalar() or 0.0
        avg_days = base.with_entities(func.avg(TradeOutcome.holding_days)).scalar() or 0.0
        best = base.with_entities(func.max(TradeOutcome.pnl_pct)).scalar()
        worst = base.with_entities(func.min(TradeOutcome.pnl_pct)).scalar()
        return OutcomesStatsSchema(
            total_trades=total,
            win_rate_pct=round(win_rate, 2),
            avg_pnl_pct=round(float(avg_pnl), 2),
            avg_holding_days=round(float(avg_days), 2),
            best_trade_pct=round(best, 2) if best is not None else None,
            worst_trade_pct=round(worst, 2) if worst is not None else None,
        )
    finally:
        session.close()


@router.get("/{outcome_id}/timeline", response_model=TradeTimelineSchema)
async def get_outcome_timeline(outcome_id: int):
    """Daily price series and buy/sell annotations for one completed trade."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        payload = build_trade_timeline(session, outcome_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Trade outcome not found")
        if not payload.get("prices"):
            raise HTTPException(
                status_code=502,
                detail="Price history unavailable for this ticker and date range",
            )
        return payload
    finally:
        session.close()
