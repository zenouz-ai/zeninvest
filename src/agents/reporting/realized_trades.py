"""Eligibility rules for realized (non-simulated) closed trades."""

from __future__ import annotations

from sqlalchemy.orm import Query, Session, aliased

from src.data.models import Order, TradeOutcome

REALIZED_ORDER_STATUS = "filled"
SIMULATED_RUN_TYPE = "dry_run"


def is_realized_exit_order(order: Order) -> bool:
    """True when an exit order represents an actual closed position."""
    action = str(order.action or "").strip().upper()
    status = str(order.status or "").strip().lower()
    return action in {"SELL", "REDUCE"} and status == REALIZED_ORDER_STATUS


def is_realized_entry_order(order: Order) -> bool:
    """True when a BUY order represents an actual entry fill."""
    action = str(order.action or "").strip().upper()
    status = str(order.status or "").strip().lower()
    return action == "BUY" and status == REALIZED_ORDER_STATUS


def realized_exit_orders_query(session: Session) -> Query:
    """Orders eligible to create or rebuild trade_outcomes rows."""
    return (
        session.query(Order)
        .filter(
            Order.action.in_(["SELL", "REDUCE"]),
            Order.status == REALIZED_ORDER_STATUS,
        )
    )


def realized_trade_outcomes_query(session: Session) -> Query:
    """TradeOutcome rows whose linked buy and sell orders are both filled."""
    buy_order = aliased(Order)
    sell_order = aliased(Order)
    return (
        session.query(TradeOutcome)
        .join(buy_order, buy_order.id == TradeOutcome.buy_order_id)
        .join(sell_order, sell_order.id == TradeOutcome.sell_order_id)
        .filter(
            buy_order.status == REALIZED_ORDER_STATUS,
            sell_order.status == REALIZED_ORDER_STATUS,
        )
    )


def count_realized_trade_outcomes(session: Session) -> int:
    """Count closed trades with filled entry and exit orders."""
    return int(realized_trade_outcomes_query(session).count())
