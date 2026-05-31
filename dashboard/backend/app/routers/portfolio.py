"""Portfolio router - current holdings and portfolio history."""

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from src.data.database import get_session
from src.data.models import PortfolioSnapshot, Instrument, Order
from src.utils.config import get_settings

from ..schemas import PortfolioHistoryStartSchema, PortfolioSnapshotSchema, PositionSchema

router = APIRouter()
settings = get_settings()


def _parse_position(pos_data: dict, session: Session) -> PositionSchema:
    """Parse position from stored JSON — supports both T212 (instrument.ticker, walletImpact) and normalized formats."""
    ticker = (pos_data.get("instrument") or {}).get("ticker") or pos_data.get("ticker", "")
    quantity = float(pos_data.get("quantity", 0))
    wallet = pos_data.get("walletImpact") or {}
    value_gbp = float(pos_data.get("value_gbp", 0)) or float(wallet.get("currentValue", 0))
    if not value_gbp and quantity and pos_data.get("currentPrice"):
        value_gbp = quantity * float(pos_data.get("currentPrice", 0))
    pnl_gbp = float(pos_data.get("pnl_gbp", 0)) or float(wallet.get("unrealizedProfitLoss", 0))
    total_cost = float(wallet.get("totalCost", 0))
    pnl_pct = float(pos_data.get("pnl_pct", 0)) or ((pnl_gbp / total_cost * 100) if total_cost else 0)
    instrument = session.query(Instrument).filter(Instrument.ticker == ticker).first()
    sector = instrument.sector if instrument else None
    held_hours = pos_data.get("held_hours")
    held_days = pos_data.get("held_days")
    ppd_pct = pos_data.get("profit_per_day_pct")
    if ppd_pct is None and held_hours not in (None, 0) and pnl_pct:
        try:
            hh = float(held_hours)
            if hh > 0:
                ppd_pct = round(pnl_pct / (hh / 24.0), 4)
        except (TypeError, ValueError):
            ppd_pct = None
    return PositionSchema(
        ticker=ticker,
        quantity=quantity,
        value_gbp=value_gbp,
        pnl_gbp=pnl_gbp,
        pnl_pct=pnl_pct,
        sector=sector,
        profit_lock_status=pos_data.get("profit_lock_status"),
        profit_lock_required_price_gbp=pos_data.get("profit_lock_required_price_gbp"),
        profit_lock_stop_price_gbp=pos_data.get("profit_lock_stop_price_gbp"),
        profit_lock_protected_qty=pos_data.get("profit_lock_protected_qty"),
        held_hours=float(held_hours) if isinstance(held_hours, (int, float)) else None,
        held_days=float(held_days) if isinstance(held_days, (int, float)) else None,
        profit_per_day_pct=float(ppd_pct) if isinstance(ppd_pct, (int, float)) else None,
    )


@router.get("/", response_model=PortfolioSnapshotSchema)
async def get_portfolio():
    """Get current portfolio snapshot (latest)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        snapshot = (
            session.query(PortfolioSnapshot)
            .order_by(desc(PortfolioSnapshot.timestamp))
            .first()
        )

        if not snapshot:
            raise HTTPException(status_code=404, detail="No portfolio snapshot found")

        # Parse positions JSON (T212 or normalized format)
        positions_data = json.loads(snapshot.positions_json) if snapshot.positions_json else []
        positions = [_parse_position(p, session) for p in positions_data]

        return PortfolioSnapshotSchema(
            timestamp=snapshot.timestamp,
            total_value_gbp=snapshot.total_value_gbp,
            cash_gbp=snapshot.cash_gbp,
            invested_gbp=snapshot.invested_gbp,
            pnl_gbp=snapshot.pnl_gbp,
            pnl_pct=snapshot.pnl_pct,
            num_positions=snapshot.num_positions,
            positions=positions,
        )
    finally:
        session.close()


@router.get("/history", response_model=list[PortfolioSnapshotSchema])
async def get_portfolio_history(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
):
    """Get portfolio history with pagination."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        query = session.query(PortfolioSnapshot)

        if start_date:
            query = query.filter(PortfolioSnapshot.timestamp >= start_date)

        if end_date:
            query = query.filter(PortfolioSnapshot.timestamp <= end_date)

        snapshots = query.order_by(desc(PortfolioSnapshot.timestamp)).offset(offset).limit(limit).all()

        result = []
        for snapshot in snapshots:
            positions_data = json.loads(snapshot.positions_json) if snapshot.positions_json else []
            positions = [_parse_position(p, session) for p in positions_data]

            result.append(
                PortfolioSnapshotSchema(
                    timestamp=snapshot.timestamp,
                    total_value_gbp=snapshot.total_value_gbp,
                    cash_gbp=snapshot.cash_gbp,
                    invested_gbp=snapshot.invested_gbp,
                    pnl_gbp=snapshot.pnl_gbp,
                    pnl_pct=snapshot.pnl_pct,
                    num_positions=snapshot.num_positions,
                    positions=positions,
                )
            )

        return result
    finally:
        session.close()


@router.get("/history-start", response_model=PortfolioHistoryStartSchema)
async def get_portfolio_history_start():
    """Get the earliest order timestamp used to anchor the portfolio history chart."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        first_order = session.query(Order.timestamp).order_by(asc(Order.timestamp)).first()
        timestamp = first_order[0] if first_order else None
        return PortfolioHistoryStartSchema(timestamp=timestamp)
    finally:
        session.close()
