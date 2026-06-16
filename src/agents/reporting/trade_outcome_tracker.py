"""Trade outcome tracking: link BUY orders to SELL/REDUCE and record P&L with conviction and moderator linkage."""

from typing import Any

from sqlalchemy.orm import Session

from src.agents.execution.order_wallet import effective_filled_shares, fifo_wallet_slice, wallet_value_gbp
from src.agents.reporting.realized_trades import (
    REALIZED_ORDER_STATUS,
    is_realized_exit_order,
    realized_exit_orders_query,
)
from src.data.models import Order, TradeOutcome
from src.utils.datetime_utils import ensure_utc_datetime
from src.utils.logger import get_logger

logger = get_logger("trade_outcome_tracker")


def update_trade_outcomes(session: Session | None = None) -> int:
    """Find filled SELL/REDUCE orders not yet in trade_outcomes, match FIFO to BUYs, and insert outcomes.

    Returns:
        Number of new trade_outcome rows created.
    """
    from src.data.database import get_session

    own_session = session is None
    if session is None:
        session = get_session()
    try:
        recorded = {row[0] for row in session.query(TradeOutcome.sell_order_id).all()}

        sell_orders = (
            realized_exit_orders_query(session)
            .filter(Order.id.notin_(recorded) if recorded else True)
            .order_by(Order.timestamp)
            .all()
        )

        created = 0
        for sell_order in sell_orders:
            outcome = _match_sell_to_buys(session, sell_order)
            if outcome:
                session.add(outcome)
                created += 1
        if created:
            session.commit()
        return created
    except Exception as e:
        logger.error(f"Trade outcome update failed: {e}")
        session.rollback()
        return 0
    finally:
        if own_session:
            session.close()


def recompute_trade_outcomes(session: Session | None = None) -> int:
    """Rebuild all trade_outcomes rows from reconciled T212 wallet fields."""
    from src.data.database import get_session

    own_session = session is None
    if session is None:
        session = get_session()
    updated = 0
    try:
        session.query(TradeOutcome).delete()
        sell_orders = (
            realized_exit_orders_query(session)
            .order_by(Order.timestamp)
            .all()
        )
        for sell_order in sell_orders:
            outcome = _match_sell_to_buys(session, sell_order)
            if outcome:
                session.add(outcome)
                updated += 1
        session.commit()
        return updated
    except Exception as e:
        logger.error(f"Trade outcome recompute failed: {e}")
        session.rollback()
        return 0
    finally:
        if own_session:
            session.close()


def _match_sell_to_buys(session: Session, sell_order: Order) -> TradeOutcome | None:
    """Match one SELL/REDUCE order to prior BUYs (FIFO), compute P&L and return one TradeOutcome."""
    if not is_realized_exit_order(sell_order):
        return None

    ticker = sell_order.ticker
    sell_qty = effective_filled_shares(sell_order)
    if sell_qty <= 0:
        sell_qty = abs(float(sell_order.quantity or 0))
    sell_value = wallet_value_gbp(sell_order) or 0.0
    if sell_qty <= 0:
        return None

    sell_ts_utc = ensure_utc_datetime(sell_order.timestamp)
    if sell_ts_utc is None:
        return None
    sell_cutoff = sell_ts_utc.replace(tzinfo=None)

    buys = (
        session.query(Order)
        .filter(
            Order.ticker == ticker,
            Order.action == "BUY",
            Order.status == REALIZED_ORDER_STATUS,
            Order.timestamp < sell_cutoff,
        )
        .order_by(Order.timestamp.asc())
        .all()
    )

    remaining = sell_qty
    buy_value_total = 0.0
    first_buy: Order | None = None
    first_buy_ts = None

    for buy in buys:
        if remaining <= 0:
            break
        buy_qty = effective_filled_shares(buy)
        if buy_qty <= 0:
            buy_qty = float(buy.quantity or 0)
        if buy_qty <= 0:
            continue
        if first_buy is None:
            first_buy = buy
            first_buy_ts = buy.timestamp
        take = min(remaining, buy_qty)
        slice_wallet = fifo_wallet_slice(buy, take)
        if slice_wallet is None:
            buy_wallet = wallet_value_gbp(buy) or float(buy.value_gbp or 0)
            slice_wallet = buy_wallet * (take / buy_qty)
        buy_value_total += slice_wallet
        remaining -= take

    if remaining > 0.01:
        logger.debug(f"Trade outcome: sell {ticker} qty {sell_qty} only matched {sell_qty - remaining:.2f} from BUYs")
        if buy_value_total <= 0:
            return None
        matched_qty = sell_qty - remaining
        if sell_value > 0 and sell_qty > 0:
            sell_value = sell_value * (matched_qty / sell_qty)

    if buy_value_total <= 0 or sell_value <= 0:
        return None

    pnl_gbp = sell_value - buy_value_total
    pnl_pct = (pnl_gbp / buy_value_total * 100) if buy_value_total else 0
    first_buy_utc = ensure_utc_datetime(first_buy_ts) if first_buy_ts else None
    holding_days = (
        (sell_ts_utc - first_buy_utc).total_seconds() / 86400.0 if first_buy_utc else None
    )

    return TradeOutcome(
        buy_order_id=first_buy.id if first_buy else None,
        sell_order_id=sell_order.id,
        ticker=ticker,
        buy_timestamp=first_buy_ts,
        sell_timestamp=sell_order.timestamp,
        holding_days=holding_days,
        buy_value_gbp=buy_value_total,
        sell_value_gbp=sell_value,
        pnl_gbp=pnl_gbp,
        pnl_pct=pnl_pct,
        conviction=first_buy.conviction if first_buy else sell_order.conviction,
        strategy=first_buy.strategy if first_buy else sell_order.strategy,
        moderation_result=first_buy.moderation_result if first_buy else sell_order.moderation_result,
        risk_result=first_buy.risk_result if first_buy else sell_order.risk_result,
    )
