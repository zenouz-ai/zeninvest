"""API usage router — api_logs daily counts and error rates."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func

from src.data.database import get_session
from src.data.models import ApiLog
from src.utils.config import get_settings

from ..schemas import ApiUsageDailySchema

router = APIRouter()
settings = get_settings()


@router.get("/daily", response_model=list[ApiUsageDailySchema])
async def get_api_usage_daily(
    days: int = Query(default=14, ge=1, le=90),
):
    """Daily API call counts and error rates by service."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        start = datetime.now(timezone.utc) - timedelta(days=days)
        rows = (
            session.query(
                func.date(ApiLog.timestamp).label("day"),
                ApiLog.service,
                func.count(ApiLog.id).label("calls"),
                func.sum(case((ApiLog.status_code >= 400, 1), else_=0)).label("errors"),
            )
            .filter(ApiLog.timestamp >= start)
            .group_by(func.date(ApiLog.timestamp), ApiLog.service)
            .all()
        )
        by_date: dict[str, dict[str, dict]] = {}
        for row in rows:
            day = row.day.isoformat() if hasattr(row.day, "isoformat") else str(row.day)
            if day not in by_date:
                by_date[day] = {}
            calls = int(row.calls or 0)
            errors = int(row.errors or 0)
            by_date[day][row.service] = {
                "calls": calls,
                "errors": errors,
                "error_rate": round(errors / calls * 100, 2) if calls else 0,
            }
        result = [
            ApiUsageDailySchema(date=d, by_service=by_date[d])
            for d in sorted(by_date.keys(), reverse=True)[:days]
        ]
        return result
    finally:
        session.close()
