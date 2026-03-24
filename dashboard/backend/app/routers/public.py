"""Explicit public dashboard routes."""

from fastapi import APIRouter, HTTPException, Query

from src.utils.config import get_settings

from ..routers.costs import get_costs_daily, get_costs_monthly
from ..routers.docs import get_doc
from ..routers.performance import get_latest_metrics
from ..schemas import (
    PerformanceMetricSchema,
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
