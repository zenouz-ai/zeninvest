"""Opportunity router — UOV scores and queue."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc

from src.data.database import get_session
from src.data.models import OpportunityQueue, OpportunityScoreSnapshot
from src.utils.config import get_settings

from ..schemas import OpportunityConfigSchema, OpportunityQueueSchema, OpportunityScoreSchema

router = APIRouter()
settings = get_settings()


@router.get("/scores/", response_model=list[OpportunityScoreSchema])
async def list_scores(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    cycle_id: str | None = Query(default=None),
    ticker: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
):
    """Latest UOV scores, paginated and filterable."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        query = session.query(OpportunityScoreSnapshot)
        if cycle_id:
            query = query.filter(OpportunityScoreSnapshot.cycle_id == cycle_id)
        if ticker:
            query = query.filter(OpportunityScoreSnapshot.ticker == ticker)
        if start_date:
            query = query.filter(OpportunityScoreSnapshot.timestamp >= start_date)
        if end_date:
            query = query.filter(OpportunityScoreSnapshot.timestamp <= end_date)
        rows = query.order_by(desc(OpportunityScoreSnapshot.timestamp)).offset(offset).limit(limit).all()
        return rows
    finally:
        session.close()


@router.get("/scores/{cycle_id}", response_model=list[OpportunityScoreSchema])
async def get_scores_by_cycle(cycle_id: str):
    """UOV scores for a specific cycle."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        rows = (
            session.query(OpportunityScoreSnapshot)
            .filter(OpportunityScoreSnapshot.cycle_id == cycle_id)
            .order_by(OpportunityScoreSnapshot.ticker)
            .all()
        )
        return rows
    finally:
        session.close()


@router.get("/config/", response_model=OpportunityConfigSchema)
async def get_config():
    """Opportunity pipeline config for dashboard display (TTL, thresholds)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    return OpportunityConfigSchema(
        queue_ttl_cycles=settings.opportunity_queue_ttl_cycles,
        immediate_threshold_z=settings.opportunity_immediate_threshold_z,
    )


@router.get("/queue/", response_model=list[OpportunityQueueSchema])
async def get_queue():
    """Current opportunity queue."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        rows = (
            session.query(OpportunityQueue)
            .order_by(OpportunityQueue.last_uov_ewma.desc())
            .all()
        )
        return rows
    finally:
        session.close()


@router.get("/history/{ticker}", response_model=list[OpportunityScoreSchema])
async def get_history_by_ticker(
    ticker: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """UOV score history for a ticker (for heatmap)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        rows = (
            session.query(OpportunityScoreSnapshot)
            .filter(OpportunityScoreSnapshot.ticker == ticker)
            .order_by(desc(OpportunityScoreSnapshot.timestamp))
            .offset(offset)
            .limit(limit)
            .all()
        )
        return rows
    finally:
        session.close()
