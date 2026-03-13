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
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "results_json": r.results_json[:500] if r.results_json else None,
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
    """Aggregated research stats: total calls, by member, cache hit rate."""
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
        hits = cache_hits

        member_query = (
            session.query(ResearchLog.member, func.count(ResearchLog.id).label("cnt"))
            .group_by(ResearchLog.member)
        )
        if from_date:
            member_query = member_query.filter(ResearchLog.created_at >= from_date)
        if to_date:
            member_query = member_query.filter(ResearchLog.created_at <= to_date)
        by_member = {r.member: r.cnt for r in member_query.all()}

        return {
            "total_calls": total,
            "cache_hits": hits,
            "cache_hit_rate": (hits / total) if total > 0 else 0,
            "by_member": by_member,
        }
    finally:
        session.close()
