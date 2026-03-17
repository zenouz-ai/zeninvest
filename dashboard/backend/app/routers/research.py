"""Research router — logs and summary for agentic research tool calls."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, func

from src.data.database import get_session
from src.data.models import ResearchLog
from src.utils.config import get_settings

router = APIRouter()
settings = get_settings()


@router.get("/logs")
async def get_research_logs(
    cycle_id: str | None = Query(default=None),
    member: str | None = Query(default=None),
    ticker: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Paginated research logs with optional filters."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        query = session.query(ResearchLog)
        if cycle_id:
            query = query.filter(ResearchLog.cycle_id == cycle_id)
        if member:
            query = query.filter(ResearchLog.member == member)
        if ticker:
            query = query.filter(ResearchLog.ticker == ticker)
        rows = (
            query.order_by(desc(ResearchLog.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "cycle_id": r.cycle_id,
                "member": r.member,
                "ticker": r.ticker,
                "tool_name": r.tool_name,
                "query": r.query,
                "num_results": r.num_results,
                "provider": r.provider,
                "cache_hit": r.cache_hit,
                "latency_ms": r.latency_ms,
                "cost_usd": r.cost_usd,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "results_json": r.results_json[:500] if r.results_json else None,
            }
            for r in rows
        ]
    finally:
        session.close()


@router.get("/ticker/{ticker}")
async def get_research_by_ticker(
    ticker: str,
    limit: int = Query(default=50, ge=1, le=200),
):
    """All research logs for a given ticker, most recent first."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        rows = (
            session.query(ResearchLog)
            .filter(ResearchLog.ticker == ticker)
            .order_by(desc(ResearchLog.created_at))
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "cycle_id": r.cycle_id,
                "member": r.member,
                "tool_name": r.tool_name,
                "query": r.query,
                "num_results": r.num_results,
                "provider": r.provider,
                "cache_hit": r.cache_hit,
                "latency_ms": r.latency_ms,
                "cost_usd": r.cost_usd,
                "results_json": r.results_json[:500] if r.results_json else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    finally:
        session.close()


@router.get("/summary")
async def get_research_summary(
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
):
    """Aggregated research stats: calls, cache hit rate, cost breakdowns."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        q_base = session.query(ResearchLog)
        if from_date:
            q_base = q_base.filter(ResearchLog.created_at >= from_date)
        if to_date:
            q_base = q_base.filter(ResearchLog.created_at <= to_date)

        total = q_base.count()
        cache_hits = q_base.filter(ResearchLog.cache_hit == True).count()

        def _apply_date_filter(q):
            if from_date:
                q = q.filter(ResearchLog.created_at >= from_date)
            if to_date:
                q = q.filter(ResearchLog.created_at <= to_date)
            return q

        # Calls and cost by member
        member_rows = _apply_date_filter(
            session.query(
                ResearchLog.member,
                func.count(ResearchLog.id).label("cnt"),
                func.coalesce(func.sum(ResearchLog.cost_usd), 0.0).label("cost"),
            ).group_by(ResearchLog.member)
        ).all()
        by_member = {r.member: {"calls": r.cnt, "cost_usd": round(float(r.cost), 4)} for r in member_rows}

        # Calls and cost by tool
        tool_rows = _apply_date_filter(
            session.query(
                ResearchLog.tool_name,
                func.count(ResearchLog.id).label("cnt"),
                func.coalesce(func.sum(ResearchLog.cost_usd), 0.0).label("cost"),
            ).group_by(ResearchLog.tool_name)
        ).all()
        by_tool = {r.tool_name: {"calls": r.cnt, "cost_usd": round(float(r.cost), 4)} for r in tool_rows}

        # Calls and cost by provider
        provider_rows = _apply_date_filter(
            session.query(
                ResearchLog.provider,
                func.count(ResearchLog.id).label("cnt"),
                func.coalesce(func.sum(ResearchLog.cost_usd), 0.0).label("cost"),
            ).group_by(ResearchLog.provider)
        ).all()
        by_provider = {
            (r.provider or "unknown"): {"calls": r.cnt, "cost_usd": round(float(r.cost), 4)}
            for r in provider_rows
        }

        total_cost_usd = sum(m["cost_usd"] for m in by_member.values())
        avg_latency_ms = _apply_date_filter(
            session.query(func.avg(ResearchLog.latency_ms))
        ).scalar()

        return {
            "total_calls": total,
            "cache_hits": cache_hits,
            "cache_hit_rate": round((cache_hits / total), 4) if total > 0 else 0,
            "total_cost_usd": round(total_cost_usd, 4),
            "avg_latency_ms": round(float(avg_latency_ms), 1) if avg_latency_ms else None,
            "by_member": by_member,
            "by_tool": by_tool,
            "by_provider": by_provider,
        }
    finally:
        session.close()
