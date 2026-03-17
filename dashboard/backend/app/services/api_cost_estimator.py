"""Estimate API costs from api_logs call counts. Uses published pricing (2026-03)."""

from datetime import datetime, timezone

from sqlalchemy import func

from src.data.database import get_session
from src.data.models import ApiLog, ResearchLog

# Per-call cost estimates in GBP (from CLAUDE.md pricing, USD→GBP ~0.79)
# brave_search: $5/1000; brave_answers: $4/1000 base; tavily: ~$0.008/credit
# t212, finnhub, alpha_vantage, yfinance: free tiers
_COST_PER_CALL_GBP: dict[str, float] = {
    "brave_search": 0.004,   # $5/1000 ≈ £0.004
    "brave_answers": 0.003,  # $4/1000 ≈ £0.003
    "tavily": 0.006,         # ~$0.008/credit
    "t212": 0.0,
    "finnhub": 0.0,
    "alpha_vantage": 0.0,
    "yfinance": 0.0,
}


def estimate_api_cost_gbp(
    start: datetime,
    end: datetime,
) -> float:
    """Estimate total API cost (GBP) for the given time range from api_logs."""
    session = get_session()
    try:
        rows = (
            session.query(ApiLog.service, func.count(ApiLog.id).label("calls"))
            .filter(
                ApiLog.timestamp >= start,
                ApiLog.timestamp <= end,
            )
            .group_by(ApiLog.service)
            .all()
        )
        total = 0.0
        for service, calls in rows:
            rate = _COST_PER_CALL_GBP.get(service, 0.0)
            total += int(calls or 0) * rate
        return round(total, 4)
    finally:
        session.close()


def get_api_cost_by_day(start: datetime, end: datetime) -> dict[str, float]:
    """Return {date_str: api_cost_gbp} for each day in range."""
    session = get_session()
    try:
        rows = (
            session.query(
                func.date(ApiLog.timestamp).label("day"),
                ApiLog.service,
                func.count(ApiLog.id).label("calls"),
            )
            .filter(
                ApiLog.timestamp >= start,
                ApiLog.timestamp <= end,
            )
            .group_by(func.date(ApiLog.timestamp), ApiLog.service)
            .all()
        )
        by_date: dict[str, float] = {}
        for row in rows:
            day = row.day.isoformat() if hasattr(row.day, "isoformat") else str(row.day)
            rate = _COST_PER_CALL_GBP.get(row.service, 0.0)
            cost = int(row.calls or 0) * rate
            by_date[day] = by_date.get(day, 0.0) + cost
        return {d: round(v, 4) for d, v in by_date.items()}
    finally:
        session.close()


def get_api_cost_by_month(start: datetime, end: datetime) -> dict[str, float]:
    """Return {year_month: api_cost_gbp} for each month in range."""
    session = get_session()
    try:
        ym_expr = func.strftime("%Y-%m", ApiLog.timestamp)
        rows = (
            session.query(ym_expr.label("ym"), ApiLog.service, func.count(ApiLog.id).label("calls"))
            .filter(
                ApiLog.timestamp >= start,
                ApiLog.timestamp <= end,
            )
            .group_by(ym_expr, ApiLog.service)
            .all()
        )
        by_ym: dict[str, float] = {}
        for row in rows:
            rate = _COST_PER_CALL_GBP.get(row.service, 0.0)
            cost = int(row.calls or 0) * rate
            by_ym[row.ym] = by_ym.get(row.ym, 0.0) + cost
        return {ym: round(v, 4) for ym, v in by_ym.items()}
    finally:
        session.close()


_USD_TO_GBP = 0.79


def get_research_cost_by_day(start: datetime, end: datetime) -> dict[str, float]:
    """Return {date_str: research_cost_gbp} aggregated from research_logs.cost_usd."""
    session = get_session()
    try:
        rows = (
            session.query(
                func.date(ResearchLog.created_at).label("day"),
                func.coalesce(func.sum(ResearchLog.cost_usd), 0.0).label("cost_usd"),
            )
            .filter(ResearchLog.created_at >= start, ResearchLog.created_at <= end)
            .group_by(func.date(ResearchLog.created_at))
            .all()
        )
        return {
            (row.day.isoformat() if hasattr(row.day, "isoformat") else str(row.day)): round(
                float(row.cost_usd) * _USD_TO_GBP, 4
            )
            for row in rows
        }
    finally:
        session.close()


def get_research_cost_by_month(start: datetime, end: datetime) -> dict[str, float]:
    """Return {year_month: research_cost_gbp} aggregated from research_logs.cost_usd."""
    session = get_session()
    try:
        ym_expr = func.strftime("%Y-%m", ResearchLog.created_at)
        rows = (
            session.query(
                ym_expr.label("ym"),
                func.coalesce(func.sum(ResearchLog.cost_usd), 0.0).label("cost_usd"),
            )
            .filter(ResearchLog.created_at >= start, ResearchLog.created_at <= end)
            .group_by(ym_expr)
            .all()
        )
        return {row.ym: round(float(row.cost_usd) * _USD_TO_GBP, 4) for row in rows}
    finally:
        session.close()
