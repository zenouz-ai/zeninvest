"""Explicit public dashboard routes."""

from fastapi import APIRouter, HTTPException, Query

from src.utils.config import get_settings

from ..routers.costs import get_costs_daily, get_costs_monthly
from ..routers.docs import get_doc
from ..routers.macro import (
    get_headlines,
    get_latest_state,
    get_macro_summary,
    get_state_history,
)
from ..routers.performance import get_latest_metrics
from ..routers.portfolio import get_portfolio, get_portfolio_history
from ..routers.portfolio import get_portfolio_history_start
from ..schemas import (
    MacroHeadlineSchema,
    MacroStateSchema,
    MacroSummarySchema,
    PerformanceMetricSchema,
    PortfolioHistoryStartSchema,
    PortfolioSnapshotSchema,
    PublicCostDailySchema,
    PublicCostMonthlySchema,
)

router = APIRouter()
settings = get_settings()


@router.get("/docs/{doc_key}")
async def get_public_doc(doc_key: str):
    """Serve public roadmap / architecture docs."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")
    return await get_doc(doc_key)


@router.get("/costs/daily", response_model=list[PublicCostDailySchema])
async def get_public_costs_daily(
    days: int = Query(default=30, ge=1, le=365),
):
    """Sanitized daily aggregate cost summary."""
    rows = await get_costs_daily(days=days)
    return [
        PublicCostDailySchema(
            date=row.date,
            total_gbp=row.total_gbp + row.api_cost_gbp + row.research_cost_gbp,
            llm_cost_gbp=row.llm_cost_gbp,
            api_cost_gbp=row.api_cost_gbp,
            research_cost_gbp=row.research_cost_gbp,
        )
        for row in rows
    ]


@router.get("/costs/monthly", response_model=list[PublicCostMonthlySchema])
async def get_public_costs_monthly(
    months: int = Query(default=12, ge=1, le=24),
):
    """Sanitized monthly aggregate cost summary."""
    rows = await get_costs_monthly(months=months)
    return [
        PublicCostMonthlySchema(
            year_month=row.year_month,
            total_gbp=row.total_gbp,
            llm_cost_gbp=row.llm_cost_gbp,
            api_cost_gbp=row.api_cost_gbp,
            research_cost_gbp=row.research_cost_gbp,
        )
        for row in rows
    ]


@router.get("/performance/metrics", response_model=PerformanceMetricSchema | None)
async def get_public_performance_metrics():
    """Public aggregate performance snapshot."""
    return await get_latest_metrics()


@router.get("/portfolio", response_model=PortfolioSnapshotSchema)
async def get_public_portfolio():
    """Public read-only current portfolio snapshot."""
    return await get_portfolio()


@router.get("/portfolio/history", response_model=list[PortfolioSnapshotSchema])
async def get_public_portfolio_history(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Public read-only portfolio history."""
    return await get_portfolio_history(limit=limit, offset=offset)


@router.get("/portfolio/history-start", response_model=PortfolioHistoryStartSchema)
async def get_public_portfolio_history_start():
    """Public read-only anchor timestamp for portfolio history."""
    return await get_portfolio_history_start()


@router.get("/macro/state", response_model=MacroStateSchema | None)
async def get_public_macro_state():
    """Public read-only latest macro state."""
    return await get_latest_state()


@router.get("/macro/state/history", response_model=list[MacroStateSchema])
async def get_public_macro_state_history(
    days: int = Query(default=7, ge=1, le=90),
):
    """Public read-only macro state history."""
    return await get_state_history(days=days)


@router.get("/macro/headlines", response_model=list[MacroHeadlineSchema])
async def get_public_macro_headlines(
    days: int = Query(default=7, ge=1, le=90),
    category: str = Query(default="all"),
    limit: int = Query(default=200, ge=1, le=500),
):
    """Public read-only macro headline archive."""
    return await get_headlines(days=days, category=category, limit=limit)


@router.get("/macro/summary", response_model=MacroSummarySchema)
async def get_public_macro_summary():
    """Public read-only macro summary."""
    return await get_macro_summary()
