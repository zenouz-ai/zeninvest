"""Universe router - stock universe explorer."""

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from src.data.database import get_session
from src.data.models import Instrument, ModerationLog, OpportunityScoreSnapshot, Order, PortfolioSnapshot, RiskDecision, StrategyDecision
from src.utils.config import get_settings

from ..schemas import InstrumentDetailSchema, InstrumentSchema, UniverseBubbleSchema

router = APIRouter()
settings = get_settings()


def _get_instrument_label(session: Session, ticker: str) -> tuple[str | None, dict[str, Any] | None]:
    """Get the latest decision label (buy/sell/hold/watch) and full LLM decision data for a ticker."""
    strategy = (
        session.query(StrategyDecision)
        .filter(StrategyDecision.ticker == ticker)
        .order_by(desc(StrategyDecision.timestamp))
        .first()
    )

    if not strategy:
        return None, None

    # All moderation rows for this cycle/ticker (one per moderator)
    moderation_list = (
        session.query(ModerationLog)
        .filter(ModerationLog.cycle_id == strategy.cycle_id, ModerationLog.ticker == ticker)
        .order_by(ModerationLog.timestamp)
        .all()
    )
    consensus_row = next((m for m in moderation_list if m.consensus), moderation_list[-1] if moderation_list else None)

    risk = (
        session.query(RiskDecision)
        .filter(RiskDecision.cycle_id == strategy.cycle_id, RiskDecision.ticker == ticker)
        .first()
    )

    # Label from consensus and risk
    if risk and risk.verdict == "REJECT":
        label = "rejected"
    elif consensus_row and consensus_row.consensus == "BLOCKED":
        label = "blocked"
    elif strategy.action == "BUY":
        label = "buy"
    elif strategy.action == "SELL":
        label = "sell"
    elif strategy.action == "REDUCE":
        label = "reduce"
    else:
        label = "hold"

    # Full strategy LLM output
    strategy_full: dict[str, Any] = {
        "action": strategy.action,
        "conviction": strategy.conviction,
        "primary_strategy": strategy.primary_strategy,
        "reasoning": strategy.reasoning,
        "timestamp": strategy.timestamp.isoformat(),
        "growth_potential": strategy.growth_potential,
        "risk_level": strategy.risk_level,
        "exit_conditions": strategy.exit_conditions,
        "news_sentiment_summary": strategy.news_sentiment_summary,
        "market_assessment": strategy.market_assessment,
        "portfolio_commentary": strategy.portfolio_commentary,
        "stop_loss_pct": strategy.stop_loss_pct,
        "expected_holding_period": strategy.expected_holding_period,
        "upside_target_pct": strategy.upside_target_pct,
    }
    if strategy.raw_response_json:
        try:
            strategy_full["raw_response_json"] = json.loads(strategy.raw_response_json)
        except Exception:
            strategy_full["raw_response_json"] = strategy.raw_response_json

    # All moderators' full outputs
    moderation_full = [
        {
            "moderator": m.moderator,
            "verdict": m.verdict,
            "reasoning": m.reasoning,
            "growth_score": m.growth_score,
            "risk_score": m.risk_score,
            "confidence_score": m.confidence_score,
            "consensus": m.consensus,
        }
        for m in moderation_list
    ] if moderation_list else None

    # Full risk LLM output
    risk_full: dict[str, Any] | None = None
    if risk:
        risk_full = {
            "verdict": risk.verdict,
            "reasoning": risk.reasoning,
            "adjusted_allocation_pct": risk.adjusted_allocation_pct,
            "triggered_rules_json": risk.triggered_rules_json,
            "rules_checked_json": risk.rules_checked_json,
        }
        if risk.triggered_rules_json:
            try:
                risk_full["triggered_rules"] = json.loads(risk.triggered_rules_json) if isinstance(risk.triggered_rules_json, str) else risk.triggered_rules_json
            except Exception:
                pass

    decision_data = {
        "cycle_id": strategy.cycle_id,
        "strategy": strategy_full,
        "moderation": moderation_full,
        "risk": risk_full,
    }

    return label, decision_data


@router.get("/", response_model=list[InstrumentSchema])
async def get_universe(
    limit: int = Query(default=100, ge=1, le=5000),
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


@router.get("/bubble", response_model=list[UniverseBubbleSchema])
async def get_universe_bubble(
    limit: int = Query(default=1000, ge=1, le=5000),
):
    """Universe with latest UOV per ticker and investigated flag for bubble viz."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        instruments = (
            session.query(Instrument)
            .filter(Instrument.data_available == True)
            .order_by(desc(Instrument.last_screened_at))
            .limit(limit)
            .all()
        )
        if not instruments:
            return []

        tickers = [i.ticker for i in instruments]
        # Aggregate decision stats per ticker
        decision_rows = (
            session.query(StrategyDecision.ticker, StrategyDecision.action)
            .filter(StrategyDecision.ticker.in_(tickers))
            .all()
        )
        decision_stats: dict[str, dict[str, int]] = {}
        for ticker, action in decision_rows:
            stats = decision_stats.setdefault(
                ticker,
                {"count": 0, "BUY": 0, "SELL": 0, "REDUCE": 0, "HOLD": 0},
            )
            stats["count"] += 1
            act = (action or "").upper()
            if act in ("BUY", "SELL", "REDUCE", "HOLD"):
                stats[act] += 1
        scores_rows = (
            session.query(OpportunityScoreSnapshot)
            .filter(OpportunityScoreSnapshot.ticker.in_(tickers))
            .order_by(desc(OpportunityScoreSnapshot.timestamp))
            .limit(5000)
            .all()
        )
        latest_uov: dict[str, tuple[float, float, float]] = {}
        for row in scores_rows:
            if row.ticker not in latest_uov:
                latest_uov[row.ticker] = (row.uov_raw, row.uov_z, row.uov_ewma)

        # Latest portfolio snapshot for holdings
        latest_snapshot = (
            session.query(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.timestamp.desc())
            .first()
        )
        holdings: dict[str, float] = {}
        if latest_snapshot and latest_snapshot.positions_json:
            import json

            try:
                positions = json.loads(latest_snapshot.positions_json)
                for pos in positions:
                    t = pos.get("ticker")
                    qty = float(pos.get("quantity", 0.0))
                    if t:
                        holdings[t] = holdings.get(t, 0.0) + qty
            except Exception:
                pass

        # Total sold quantity per ticker (positive = shares sold).
        # SELL orders store negative quantity; we report abs(sum(quantity)).
        # We also split into live vs dry-run components for transparency.
        sold_live_rows = (
            session.query(Order.ticker, func.sum(func.abs(Order.quantity)))
            .filter(
                Order.ticker.in_(tickers),
                Order.action == "SELL",
                Order.status == "filled",
            )
            .group_by(Order.ticker)
            .all()
        )
        sold_dry_run_rows = (
            session.query(Order.ticker, func.sum(func.abs(Order.quantity)))
            .filter(
                Order.ticker.in_(tickers),
                Order.action == "SELL",
                Order.status == "dry_run",
            )
            .group_by(Order.ticker)
            .all()
        )
        sold_live_qty: dict[str, float] = {t: float(q or 0.0) for t, q in sold_live_rows}
        sold_dry_run_qty: dict[str, float] = {t: float(q or 0.0) for t, q in sold_dry_run_rows}

        result = []
        for i in instruments:
            uov = latest_uov.get(i.ticker)
            stats = decision_stats.get(i.ticker, {"count": 0, "BUY": 0, "SELL": 0, "REDUCE": 0, "HOLD": 0})
            result.append(
                UniverseBubbleSchema(
                    ticker=i.ticker,
                    name=i.name,
                    sector=i.sector,
                    industry=i.industry,
                    market_cap=i.market_cap,
                    last_screened_at=i.last_screened_at,
                    data_available=i.data_available,
                    investigated=stats["count"] > 0,
                    uov_raw=uov[0] if uov else None,
                    uov_z=uov[1] if uov else None,
                    uov_ewma=uov[2] if uov else None,
                    decision_count=stats["count"],
                    buy_count=stats["BUY"],
                    sell_count=stats["SELL"],
                    reduce_count=stats["REDUCE"],
                    hold_count=stats["HOLD"],
                    hold_qty=holdings.get(i.ticker, 0.0),
                    sold_qty=sold_live_qty.get(i.ticker, 0.0) + sold_dry_run_qty.get(i.ticker, 0.0),
                    sold_live_qty=sold_live_qty.get(i.ticker, 0.0),
                    sold_dry_run_qty=sold_dry_run_qty.get(i.ticker, 0.0),
                )
            )
        return result
    finally:
        session.close()


@router.get("/{ticker}", response_model=InstrumentDetailSchema)
async def get_instrument(ticker: str):
    """Get detailed instrument info with latest committee reasoning and execution summary."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        instrument = session.query(Instrument).filter(Instrument.ticker == ticker).first()
        if not instrument:
            raise HTTPException(status_code=404, detail="Instrument not found")

        label, decision = _get_instrument_label(session, ticker)

        # Lightweight execution summary: latest BUY/SELL orders for this ticker
        latest_buy = (
            session.query(Order)
            .filter(Order.ticker == ticker, Order.action == "BUY")
            .order_by(desc(Order.timestamp))
            .first()
        )
        latest_sell = (
            session.query(Order)
            .filter(Order.ticker == ticker, Order.action == "SELL")
            .order_by(desc(Order.timestamp))
            .first()
        )

        execution_summary: dict[str, Any] = {}
        if latest_buy:
            execution_summary["last_buy"] = {
                "timestamp": latest_buy.timestamp.isoformat(),
                "status": latest_buy.status,
                "quantity": latest_buy.quantity,
            }
        if latest_sell:
            execution_summary["last_sell"] = {
                "timestamp": latest_sell.timestamp.isoformat(),
                "status": latest_sell.status,
                "quantity": latest_sell.quantity,
            }
        if execution_summary:
            decision = decision or {}
            decision["execution_summary"] = execution_summary

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
