"""Costs router — cost_logs, daily/monthly breakdown, degradation."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func

from src.data.database import get_session
from src.data.models import CostLog
from src.utils.config import get_settings

from ..schemas import CostDailySchema, CostMonthlySchema, DegradationSchema

router = APIRouter()
settings = get_settings()


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
        result = []
        for date_str in sorted(by_date.keys(), reverse=True)[:days]:
            p = by_date[date_str]
            total = p["anthropic"] + p["openai"] + p["google"]
            result.append(
                CostDailySchema(
                    date=date_str,
                    anthropic_gbp=round(p["anthropic"], 4),
                    openai_gbp=round(p["openai"], 4),
                    google_gbp=round(p["google"], 4),
                    total_gbp=round(total, 4),
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
        result = []
        for ym in sorted(by_ym.keys(), reverse=True)[:months]:
            p = by_ym[ym]
            result.append(
                CostMonthlySchema(
                    year_month=ym,
                    total_gbp=round(p["anthropic"] + p["openai"] + p["google"], 4),
                    by_provider=dict(p),
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
