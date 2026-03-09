"""Universe router - stock universe explorer."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.data.database import get_session
from src.data.models import Instrument, StrategyDecision, ModerationLog, RiskDecision
from src.utils.config import get_settings

from ..schemas import InstrumentDetailSchema, InstrumentSchema

router = APIRouter()
settings = get_settings()


def _get_instrument_label(session: Session, ticker: str) -> tuple[str | None, dict[str, Any] | None]:
    """Get the latest decision label (buy/sell/hold/watch) and full decision data for a ticker."""
    # Get latest strategy decision
    strategy = (
        session.query(StrategyDecision)
        .filter(StrategyDecision.ticker == ticker)
        .order_by(desc(StrategyDecision.timestamp))
        .first()
    )

    if not strategy:
        return None, None

    # Get moderation and risk decisions for the same cycle_id
    moderation = (
        session.query(ModerationLog)
        .filter(ModerationLog.cycle_id == strategy.cycle_id, ModerationLog.ticker == ticker)
        .first()
    )

    risk = (
        session.query(RiskDecision)
        .filter(RiskDecision.cycle_id == strategy.cycle_id, RiskDecision.ticker == ticker)
        .first()
    )

    # Determine label from decision
    if risk and risk.verdict == "REJECT":
        label = "rejected"
    elif moderation and moderation.verdict == "BLOCK":
        label = "blocked"
    elif strategy.action == "BUY":
        label = "buy"
    elif strategy.action == "SELL":
        label = "sell"
    elif strategy.action == "REDUCE":
        label = "reduce"
    else:
        label = "hold"

    decision_data = {
        "strategy": {
            "action": strategy.action,
            "conviction": strategy.conviction,
            "reasoning": strategy.reasoning,
            "timestamp": strategy.timestamp.isoformat(),
        },
        "moderation": {
            "verdict": moderation.verdict if moderation else None,
            "gpt_score": moderation.gpt_score if moderation else None,
            "gemini_score": moderation.gemini_score if moderation else None,
            "reasoning": moderation.reasoning if moderation else None,
        } if moderation else None,
        "risk": {
            "verdict": risk.verdict if risk else None,
            "triggered_rules": risk.triggered_rules if risk else None,
        } if risk else None,
    }

    return label, decision_data


@router.get("/", response_model=list[InstrumentSchema])
async def get_universe(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    sector: str | None = Query(default=None),
    data_available: bool | None = Query(default=True),
):
    """Get list of instruments in the universe."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        query = session.query(Instrument)

        if sector:
            query = query.filter(Instrument.sector == sector)

        if data_available is not None:
            query = query.filter(Instrument.data_available == data_available)

        instruments = query.order_by(desc(Instrument.last_screened_at)).offset(offset).limit(limit).all()
        return instruments
    finally:
        session.close()


@router.get("/{ticker}", response_model=InstrumentDetailSchema)
async def get_instrument(ticker: str):
    """Get detailed instrument info with latest committee reasoning."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        instrument = session.query(Instrument).filter(Instrument.ticker == ticker).first()
        if not instrument:
            raise HTTPException(status_code=404, detail="Instrument not found")

        label, decision = _get_instrument_label(session, ticker)

        return InstrumentDetailSchema(
            ticker=instrument.ticker,
            name=instrument.name,
            sector=instrument.sector,
            industry=instrument.industry,
            market_cap=instrument.market_cap,
            last_screened_at=instrument.last_screened_at,
            data_available=instrument.data_available,
            label=label,
            last_decision=decision,
        )
    finally:
        session.close()
