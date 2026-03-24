"""Commands router - Slack trade command audit log."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc

from src.data.database import get_session
from src.data.models import SlackCommandLog
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("dashboard.commands")
router = APIRouter()
settings = get_settings()


@router.get("/")
async def get_commands(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ticker: str | None = Query(default=None),
    action: str | None = Query(default=None),
    status: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
) -> list[dict]:
    """Get Slack trade command history with filtering and pagination."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        query = session.query(SlackCommandLog)

        if ticker:
            query = query.filter(SlackCommandLog.ticker == ticker)
        if action:
            query = query.filter(SlackCommandLog.action == action)
        if status:
            query = query.filter(SlackCommandLog.status == status)
        if start_date:
            query = query.filter(SlackCommandLog.timestamp >= start_date)
        if end_date:
            query = query.filter(SlackCommandLog.timestamp <= end_date)

        commands = (
            query.order_by(desc(SlackCommandLog.timestamp))
            .offset(offset)
            .limit(limit)
            .all()
        )

        return [
            {
                "id": cmd.id,
                "timestamp": cmd.timestamp.isoformat() if cmd.timestamp else None,
                "channel_id": cmd.channel_id,
                "user_id": cmd.user_id,
                "raw_message": cmd.raw_message,
                "ticker": cmd.ticker,
                "action": cmd.action,
                "cycle_id": cmd.cycle_id,
                "order_id": cmd.order_id,
                "status": cmd.status,
                "rejection_reason": cmd.rejection_reason,
                "response_message": cmd.response_message,
            }
            for cmd in commands
        ]
    finally:
        session.close()


@router.get("/stats")
async def get_command_stats() -> dict:
    """Get summary statistics for Slack trade commands."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        from sqlalchemy import func

        total = session.query(func.count(SlackCommandLog.id)).scalar() or 0

        by_status = dict(
            session.query(SlackCommandLog.status, func.count(SlackCommandLog.id))
            .group_by(SlackCommandLog.status)
            .all()
        )

        by_action = dict(
            session.query(SlackCommandLog.action, func.count(SlackCommandLog.id))
            .filter(SlackCommandLog.action.isnot(None))
            .group_by(SlackCommandLog.action)
            .all()
        )

        return {
            "total": total,
            "by_status": by_status,
            "by_action": by_action,
        }
    finally:
        session.close()
