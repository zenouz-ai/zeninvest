"""Costs router — cost_logs, daily/monthly breakdown, degradation, API vs LLM split."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func

from src.data.database import get_session
from src.data.models import CostLog
from src.utils.config import get_settings

from ..schemas import CostDailySchema, CostForCycleSchema, CostMonthlySchema, DegradationSchema
from ..services.api_cost_estimator import get_api_cost_by_day, get_api_cost_by_month

router = APIRouter()
settings = get_settings()


@router.get("/for-cycle", response_model=CostForCycleSchema)
async def get_cost_for_cycle(
    cycle_id: str = Query(..., description="Cycle ID to sum cost for"),
):
    """Total cost for a single run (cycle)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        rows = (
            session.query(CostLog.provider, func.sum(CostLog.cost_gbp).label("total"))
            .filter(CostLog.cycle_id == cycle_id)
            .group_by(CostLog.provider)
            .all()
        )
        by_provider = {"anthropic": 0.0, "openai": 0.0, "google": 0.0}
        for provider, total in rows:
            if provider in by_provider:
                by_provider[provider] = float(total or 0)
        total_gbp = sum(by_provider.values())
        return CostForCycleSchema(
            cycle_id=cycle_id,
            total_gbp=round(total_gbp, 4),
            by_provider=by_provider,
        )
    finally:
        session.close()


@router.get("/daily", response_model=list[CostDailySchema])
async def get_costs_daily(
    days: int = Query(default=30, ge=1, le=365),
):
    """Daily cost breakdown by provider."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        start = datetime.now(timezone.utc) - timedelta(days=days)
        end = datetime.now(timezone.utc)
        rows = (
            session.query(
                func.date(CostLog.timestamp).label("day"),
                CostLog.provider,
                func.sum(CostLog.cost_gbp).label("total"),
            )
            .filter(CostLog.timestamp >= start)
            .group_by(func.date(CostLog.timestamp), CostLog.provider)
            .all()
        )
        by_date: dict[str, dict[str, float]] = defaultdict(lambda: {"anthropic": 0.0, "openai": 0.0, "google": 0.0})
        for (day, provider, total) in rows:
            d = day.isoformat() if hasattr(day, "isoformat") else str(day)
            by_date[d][provider] = float(total or 0)
        api_by_day = get_api_cost_by_day(start, end)
        result = []
        for date_str in sorted(by_date.keys(), reverse=True)[:days]:
            p = by_date[date_str]
            llm = p["anthropic"] + p["openai"] + p["google"]
            api = api_by_day.get(date_str, 0.0)
            result.append(
                CostDailySchema(
                    date=date_str,
                    anthropic_gbp=round(p["anthropic"], 4),
                    openai_gbp=round(p["openai"], 4),
                    google_gbp=round(p["google"], 4),
                    total_gbp=round(llm, 4),
                    llm_cost_gbp=round(llm, 4),
                    api_cost_gbp=api,
                )
            )
        return result
    finally:
        session.close()


@router.get("/monthly", response_model=list[CostMonthlySchema])
async def get_costs_monthly(
    months: int = Query(default=12, ge=1, le=24),
):
    """Monthly cumulative cost by provider."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        start = datetime.now(timezone.utc) - timedelta(days=months * 31)
        end = datetime.now(timezone.utc)
        ym_expr = func.strftime("%Y-%m", CostLog.timestamp)
        rows = (
            session.query(ym_expr.label("ym"), CostLog.provider, func.sum(CostLog.cost_gbp).label("total"))
            .filter(CostLog.timestamp >= start)
            .group_by(ym_expr, CostLog.provider)
            .all()
        )
        by_ym: dict[str, dict[str, float]] = defaultdict(lambda: {"anthropic": 0.0, "openai": 0.0, "google": 0.0})
        for (ym, provider, total) in rows:
            by_ym[ym][provider] = float(total or 0)
        api_by_ym = get_api_cost_by_month(start, end)
        result = []
        for ym in sorted(by_ym.keys(), reverse=True)[:months]:
            p = by_ym[ym]
            llm = p["anthropic"] + p["openai"] + p["google"]
            api = api_by_ym.get(ym, 0.0)
            total = llm + api
            result.append(
                CostMonthlySchema(
                    year_month=ym,
                    total_gbp=round(total, 4),
                    by_provider=dict(p),
                    llm_cost_gbp=round(llm, 4),
                    api_cost_gbp=api,
                )
            )
        return result
    finally:
        session.close()


@router.get("/degradation", response_model=DegradationSchema)
async def get_degradation():
    """Current degradation state. Derived from cost_logs (no persisted state)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    try:
        from src.utils.cost_tracker import get_degradation_level

        level = get_degradation_level()
        return DegradationSchema(level=level.value, message=None)
    except Exception:
        return DegradationSchema(
            level="unknown",
            message="Degradation level not available (agent may not have run in this process)",
        )
