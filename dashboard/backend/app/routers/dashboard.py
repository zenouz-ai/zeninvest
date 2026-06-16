"""Dashboard router — monthly summary, run feed (notification-style)."""

from calendar import monthrange
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, exists, func, or_

from src.data.database import get_session
from src.data.models import CostLog, Instrument, Order, PortfolioSnapshot, StrategyDecision

from ..services.api_cost_estimator import estimate_api_cost_gbp, get_research_cost_by_month
from src.utils.config import get_settings

from ..async_utils import run_blocking
from ..database import Run
from ..schemas import (
    OrderSchema,
    RunSchema,
    StrategyDecisionSchema,
)
from .runs import _build_run_schema

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

    return await run_blocking(_get_monthly_summary_sync, year, month)


def _get_monthly_summary_sync(year: int, month: int) -> dict:
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
        research_cost_gbp = get_research_cost_by_month(start, end).get(ym, 0.0)
        cost_gbp = round(llm_cost_gbp + api_cost_gbp + research_cost_gbp, 4)

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

        # Cumulative (lifetime) stats
        cumul_screened = session.query(Instrument).filter(Instrument.last_screened_at.isnot(None)).count()
        cumul_investigated = session.query(func.count(func.distinct(StrategyDecision.ticker))).scalar() or 0
        cumul_orders = session.query(Order).count()
        # Uninvestigated base: eligible instruments (data_available) with no StrategyDecision ever
        uninvestigated_base = (
            session.query(Instrument)
            .filter(Instrument.data_available.is_(True))
            .filter(~exists().where(StrategyDecision.ticker == Instrument.ticker))
        )
        # Enriched = has sector, industry, market_cap, or business_summary
        has_enriched = or_(
            Instrument.sector.isnot(None),
            Instrument.industry.isnot(None),
            Instrument.market_cap.isnot(None),
            Instrument.business_summary.isnot(None),
        )
        cumul_uninvestigated = uninvestigated_base.count()
        cumul_uninvestigated_enriched = uninvestigated_base.filter(has_enriched).count()
        cumul_uninvestigated_not_enriched = cumul_uninvestigated - cumul_uninvestigated_enriched

        # Investigated by review count (1, 2, 3+ strategy decisions)
        review_counts_subq = (
            session.query(
                StrategyDecision.ticker,
                func.count(StrategyDecision.id).label("review_count"),
            )
            .group_by(StrategyDecision.ticker)
            .subquery()
        )
        rc = review_counts_subq.c
        investigated_1_review = (
            session.query(func.count()).select_from(review_counts_subq).filter(rc.review_count == 1).scalar()
        ) or 0
        investigated_2_reviews = (
            session.query(func.count()).select_from(review_counts_subq).filter(rc.review_count == 2).scalar()
        ) or 0
        investigated_3plus_reviews = (
            session.query(func.count()).select_from(review_counts_subq).filter(rc.review_count >= 3).scalar()
        ) or 0
        # New this month: tickers whose first StrategyDecision occurred this month
        first_decision_subq = (
            session.query(StrategyDecision.ticker, func.min(StrategyDecision.timestamp).label("first_ts"))
            .group_by(StrategyDecision.ticker)
            .subquery()
        )
        new_investigated_this_month = (
            session.query(func.count())
            .select_from(first_decision_subq)
            .filter(
                first_decision_subq.c.first_ts >= start,
                first_decision_subq.c.first_ts <= end,
            )
            .scalar()
        ) or 0

        return {
            "year": year,
            "month": month,
            "year_month": ym,
            "runs_count": runs_count,
            "cost_gbp": cost_gbp,
            "llm_cost_gbp": llm_cost_gbp,
            "api_cost_gbp": api_cost_gbp,
            "research_cost_gbp": research_cost_gbp,
            "portfolio_start_gbp": portfolio_start_gbp,
            "portfolio_end_gbp": portfolio_end_gbp,
            "pnl_gbp": pnl_gbp,
            "cumul_screened": cumul_screened,
            "cumul_investigated": cumul_investigated,
            "cumul_uninvestigated": cumul_uninvestigated,
            "cumul_uninvestigated_enriched": cumul_uninvestigated_enriched,
            "cumul_uninvestigated_not_enriched": cumul_uninvestigated_not_enriched,
            "investigated_1_review": investigated_1_review,
            "investigated_2_reviews": investigated_2_reviews,
            "investigated_3plus_reviews": investigated_3plus_reviews,
            "cumul_orders": cumul_orders,
            "new_investigated_this_month": new_investigated_this_month,
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
                "run": _build_run_schema(session, run),
                "decisions": [StrategyDecisionSchema.model_validate(d) for d in decisions],
                "orders": [OrderSchema.model_validate(o) for o in orders],
            })
        return out
    finally:
        session.close()
