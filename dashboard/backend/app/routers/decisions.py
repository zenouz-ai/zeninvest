"""Decisions router — strategy_decisions, pipeline waterfall."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.data.database import get_session
from src.data.models import ModerationLog, RiskDecision, StrategyDecision
from src.utils.config import get_settings

from ..schemas import (
    ModerationLogSchema,
    PipelineWaterfallSchema,
    RiskDecisionSchema,
    StrategyDecisionSchema,
)

router = APIRouter()
settings = get_settings()


@router.get("/", response_model=list[StrategyDecisionSchema])
async def list_decisions(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ticker: str | None = Query(default=None),
    cycle_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
):
    """List strategy decisions with pagination and filters."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        query = session.query(StrategyDecision)
        if ticker:
            query = query.filter(StrategyDecision.ticker == ticker)
        if cycle_id:
            query = query.filter(StrategyDecision.cycle_id == cycle_id)
        if action:
            query = query.filter(StrategyDecision.action == action)
        if start_date:
            query = query.filter(StrategyDecision.timestamp >= start_date)
        if end_date:
            query = query.filter(StrategyDecision.timestamp <= end_date)
        rows = query.order_by(desc(StrategyDecision.timestamp)).offset(offset).limit(limit).all()
        return rows
    finally:
        session.close()


@router.get("/waterfall")
async def get_pipeline_waterfall(
    cycle_id: str = Query(..., description="Cycle ID"),
    ticker: str = Query(..., description="Ticker"),
):
    """Get pipeline waterfall for a ticker in a cycle: strategy -> moderation -> risk."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        strategy = (
            session.query(StrategyDecision)
            .filter(StrategyDecision.cycle_id == cycle_id, StrategyDecision.ticker == ticker)
            .first()
        )
        moderation = (
            session.query(ModerationLog)
            .filter(ModerationLog.cycle_id == cycle_id, ModerationLog.ticker == ticker)
            .order_by(ModerationLog.timestamp)
            .all()
        )
        risk = (
            session.query(RiskDecision)
            .filter(RiskDecision.cycle_id == cycle_id, RiskDecision.ticker == ticker)
            .first()
        )
        return PipelineWaterfallSchema(
            cycle_id=cycle_id,
            ticker=ticker,
            strategy=StrategyDecisionSchema.model_validate(strategy) if strategy else None,
            moderation=[ModerationLogSchema.model_validate(m) for m in moderation],
            risk=RiskDecisionSchema.model_validate(risk) if risk else None,
        )
    finally:
        session.close()


@router.get("/ticker/{ticker}", response_model=list[StrategyDecisionSchema])
async def get_decisions_by_ticker(
    ticker: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Decision history for a ticker."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        rows = (
            session.query(StrategyDecision)
            .filter(StrategyDecision.ticker == ticker)
            .order_by(desc(StrategyDecision.timestamp))
            .offset(offset)
            .limit(limit)
            .all()
        )
        return rows
    finally:
        session.close()


@router.get("/{cycle_id}", response_model=list[StrategyDecisionSchema])
async def get_decisions_by_cycle(cycle_id: str):
    """All strategy decisions for a specific cycle."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        rows = (
            session.query(StrategyDecision)
            .filter(StrategyDecision.cycle_id == cycle_id)
            .order_by(StrategyDecision.ticker)
            .all()
        )
        return rows
    finally:
        session.close()
