"""Stop-loss router — current levels and adjustment history."""

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc

from src.data.database import get_session
from src.data.models import Order, PortfolioSnapshot, StopLossAdjustment
from src.utils.config import get_settings

from ..schemas import StopLossAdjustmentSchema, StopLossCurrentSchema

router = APIRouter()
settings = get_settings()


def _latest_snapshot_positions(session) -> dict[str, dict]:
    snapshot = (
        session.query(PortfolioSnapshot)
        .order_by(desc(PortfolioSnapshot.timestamp))
        .first()
    )
    if not snapshot or not snapshot.positions_json:
        return {}
    try:
        positions = json.loads(snapshot.positions_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    result: dict[str, dict] = {}
    for pos in positions:
        ticker = pos.get("ticker") or pos.get("symbol", "")
        if ticker:
            result[str(ticker)] = pos
    return result


def _with_profit_lock_fields(item: StopLossCurrentSchema, position_map: dict[str, dict]) -> StopLossCurrentSchema:
    pos = position_map.get(item.ticker, {})
    item.profit_lock_status = pos.get("profit_lock_status")
    item.profit_lock_required_price_gbp = pos.get("profit_lock_required_price_gbp")
    item.profit_lock_stop_price_gbp = pos.get("profit_lock_stop_price_gbp")
    item.profit_lock_protected_qty = pos.get("profit_lock_protected_qty")
    return item


def _current_stops_from_orders(session, position_map: dict[str, dict]) -> list[StopLossCurrentSchema]:
    """Current stop levels from open/pending stop orders (latest per ticker)."""
    orders = (
        session.query(Order.ticker, Order.stop_price, Order.status)
        .filter(Order.order_type == "stop", Order.status.in_(["pending", "filled", "dry_run"]))
        .order_by(desc(Order.timestamp))
        .all()
    )
    seen: set[str] = set()
    result: list[StopLossCurrentSchema] = []
    for ticker, stop_price, status in orders:
        if ticker not in seen:
            seen.add(ticker)
            source = "order (dry_run)" if status == "dry_run" else "order"
            result.append(_with_profit_lock_fields(
                StopLossCurrentSchema(ticker=ticker, stop_price=stop_price, source=source),
                position_map,
            ))
    return result


def _current_stops_from_adjustments(session, position_map: dict[str, dict]) -> list[StopLossCurrentSchema]:
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
            result.append(_with_profit_lock_fields(
                StopLossCurrentSchema(
                    ticker=r.ticker,
                    stop_price=r.new_stop_price,
                    source="adjustment",
                ),
                position_map,
            ))
    return result


def _positions_without_stops(position_map: dict[str, dict], tickers_with_stops: set[str]) -> list[StopLossCurrentSchema]:
    """Positions from latest portfolio snapshot that have no stop order or adjustment."""
    result: list[StopLossCurrentSchema] = []
    for pos in position_map.values():
        ticker = pos.get("ticker") or pos.get("symbol", "")
        if ticker and ticker not in tickers_with_stops:
            result.append(_with_profit_lock_fields(
                StopLossCurrentSchema(ticker=ticker, stop_price=None, source="position (no stop)"),
                position_map,
            ))
    return result


def _merge_current_stops(
    from_orders: list[StopLossCurrentSchema],
    from_adjustments: list[StopLossCurrentSchema],
) -> list[StopLossCurrentSchema]:
    """Prefer live order-backed stops, but keep adjustment-backed rows for tickers with no current order row."""
    merged: list[StopLossCurrentSchema] = []
    seen: set[str] = set()

    for item in from_orders + from_adjustments:
        if item.ticker in seen:
            continue
        merged.append(item)
        seen.add(item.ticker)

    return merged


@router.get("/current", response_model=list[StopLossCurrentSchema])
async def get_current_stops():
    """Current stop-loss levels for all positions (from orders, adjustments, then positions without stops)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        position_map = _latest_snapshot_positions(session)
        from_orders = _current_stops_from_orders(session, position_map)
        from_adjustments = _current_stops_from_adjustments(session, position_map)
        tickers_with_stops = {c.ticker for c in from_orders} | {c.ticker for c in from_adjustments}
        result = _merge_current_stops(from_orders, from_adjustments)
        # Add positions that have no stop order or adjustment
        missing = _positions_without_stops(position_map, tickers_with_stops)
        return result + missing
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
