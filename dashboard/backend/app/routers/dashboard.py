"""Dashboard router — monthly summary, run feed (notification-style)."""

from calendar import monthrange
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, func

from src.data.database import get_session
from src.data.models import CostLog, Order, PortfolioSnapshot, StrategyDecision

from ..services.api_cost_estimator import estimate_api_cost_gbp
from src.utils.config import get_settings

from ..database import Run
from ..schemas import (
    OrderSchema,
    RunSchema,
    StrategyDecisionSchema,
)

router = APIRouter()
settings = get_settings()


@router.get("/monthly-summary")
async def get_monthly_summary(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
):
    """Runs count, cost, and portfolio movement for the given month."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    start = datetime(year, month, 1, tzinfo=timezone.utc)
    _, last_day = monthrange(year, month)
    end = datetime(year, month, last_day, 23, 59, 59, 999999, tzinfo=timezone.utc)

    session = get_session()
    try:
        runs_count = (
            session.query(func.count(Run.id))
            .filter(Run.started_at >= start, Run.started_at <= end)
            .scalar()
        ) or 0

        ym = f"{year}-{month:02d}"
        cost_rows = (
            session.query(func.sum(CostLog.cost_gbp))
            .filter(
                CostLog.timestamp >= start,
                CostLog.timestamp <= end,
            )
            .scalar()
        )
        llm_cost_gbp = round(float(cost_rows or 0), 4)
        api_cost_gbp = estimate_api_cost_gbp(start, end)
        cost_gbp = round(llm_cost_gbp + api_cost_gbp, 4)

        snap_first = (
            session.query(PortfolioSnapshot)
            .filter(PortfolioSnapshot.timestamp >= start)
            .order_by(PortfolioSnapshot.timestamp.asc())
            .first()
        )
        snap_last = (
            session.query(PortfolioSnapshot)
            .filter(PortfolioSnapshot.timestamp <= end)
            .order_by(desc(PortfolioSnapshot.timestamp))
            .first()
        )
        portfolio_start_gbp = float(snap_first.total_value_gbp) if snap_first else None
        portfolio_end_gbp = float(snap_last.total_value_gbp) if snap_last else None
        pnl_gbp = None
        if portfolio_start_gbp is not None and portfolio_end_gbp is not None and portfolio_start_gbp != 0:
            pnl_gbp = round(portfolio_end_gbp - portfolio_start_gbp, 2)

        return {
            "year": year,
            "month": month,
            "year_month": ym,
            "runs_count": runs_count,
            "cost_gbp": cost_gbp,
            "llm_cost_gbp": llm_cost_gbp,
            "api_cost_gbp": api_cost_gbp,
            "portfolio_start_gbp": portfolio_start_gbp,
            "portfolio_end_gbp": portfolio_end_gbp,
            "pnl_gbp": pnl_gbp,
        }
    finally:
        session.close()


@router.get("/run-feed")
async def get_run_feed(
    limit: int = Query(default=20, ge=1, le=50),
):
    """Runs with full decisions and orders (notification-style, untruncated). Organised by run time."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        runs = (
            session.query(Run)
            .order_by(desc(Run.started_at))
            .limit(limit)
            .all()
        )
        out = []
        for run in runs:
            decisions = (
                session.query(StrategyDecision)
                .filter(StrategyDecision.cycle_id == run.cycle_id)
                .order_by(StrategyDecision.ticker)
                .all()
            )
            run_end = run.completed_at or (run.started_at + timedelta(hours=1))
            orders = (
                session.query(Order)
                .filter(
                    Order.timestamp >= run.started_at,
                    Order.timestamp <= run_end,
                )
                .order_by(Order.timestamp)
                .all()
            )
            out.append({
                "run": RunSchema.model_validate(run),
                "decisions": [StrategyDecisionSchema.model_validate(d) for d in decisions],
                "orders": [OrderSchema.model_validate(o) for o in orders],
            })
        return out
    finally:
        session.close()
