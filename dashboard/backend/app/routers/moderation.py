"""Moderation router — moderation_logs."""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc

from src.data.database import get_session
from src.data.models import ModerationLog
from src.utils.config import get_settings

from ..schemas import ModerationLogSchema

router = APIRouter()
settings = get_settings()


@router.get("/{cycle_id}", response_model=list[ModerationLogSchema])
async def get_moderation_by_cycle(cycle_id: str):
    """Moderation logs for a cycle."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        rows = (
            session.query(ModerationLog)
            .filter(ModerationLog.cycle_id == cycle_id)
            .order_by(ModerationLog.ticker, ModerationLog.timestamp)
            .all()
        )
        return rows
    finally:
        session.close()


@router.get("/ticker/{ticker}", response_model=list[ModerationLogSchema])
async def get_moderation_by_ticker(
    ticker: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Moderation history for a ticker."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        rows = (
            session.query(ModerationLog)
            .filter(ModerationLog.ticker == ticker)
            .order_by(desc(ModerationLog.timestamp))
            .offset(offset)
            .limit(limit)
            .all()
        )
        return rows
    finally:
        session.close()
