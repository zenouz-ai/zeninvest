"""Stop-loss router — current levels and adjustment history."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc

from src.data.database import get_session
from src.data.models import Order, StopLossAdjustment
from src.utils.config import get_settings

from ..schemas import StopLossAdjustmentSchema, StopLossCurrentSchema

router = APIRouter()
settings = get_settings()


def _current_stops_from_orders(session) -> list[StopLossCurrentSchema]:
    """Current stop levels from open/pending stop orders (latest per ticker)."""
    orders = (
        session.query(Order.ticker, Order.stop_price)
        .filter(Order.order_type == "stop", Order.status.in_(["pending", "filled"]))
        .order_by(desc(Order.timestamp))
        .all()
    )
    seen: set[str] = set()
    result: list[StopLossCurrentSchema] = []
    for ticker, stop_price in orders:
        if ticker not in seen:
            seen.add(ticker)
            result.append(
                StopLossCurrentSchema(ticker=ticker, stop_price=stop_price, source="order")
            )
    return result


def _current_stops_from_adjustments(session) -> list[StopLossCurrentSchema]:
    """Current stop levels from latest adjustment per ticker."""
    rows = (
        session.query(StopLossAdjustment)
        .order_by(desc(StopLossAdjustment.timestamp))
        .all()
    )
    seen: set[str] = set()
    result: list[StopLossCurrentSchema] = []
    for r in rows:
        if r.ticker not in seen:
            seen.add(r.ticker)
            result.append(
                StopLossCurrentSchema(
                    ticker=r.ticker,
                    stop_price=r.new_stop_price,
                    source="adjustment",
                )
            )
    return result


@router.get("/current", response_model=list[StopLossCurrentSchema])
async def get_current_stops():
    """Current stop-loss levels for all positions (from orders, then adjustments)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        from_orders = _current_stops_from_orders(session)
        if from_orders:
            return from_orders
        return _current_stops_from_adjustments(session)
    finally:
        session.close()


@router.get("/adjustments", response_model=list[StopLossAdjustmentSchema])
async def list_adjustments(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ticker: str | None = Query(default=None),
    cycle_id: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
):
    """Adjustment history, paginated."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        query = session.query(StopLossAdjustment)
        if ticker:
            query = query.filter(StopLossAdjustment.ticker == ticker)
        if cycle_id:
            query = query.filter(StopLossAdjustment.cycle_id == cycle_id)
        if start_date:
            query = query.filter(StopLossAdjustment.timestamp >= start_date)
        if end_date:
            query = query.filter(StopLossAdjustment.timestamp <= end_date)
        rows = query.order_by(desc(StopLossAdjustment.timestamp)).offset(offset).limit(limit).all()
        return rows
    finally:
        session.close()
