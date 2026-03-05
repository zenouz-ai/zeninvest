"""Trade outcome tracking: link BUY orders to SELL/REDUCE and record P&L with conviction and moderator linkage."""

from datetime import timezone
from typing import Any

from sqlalchemy.orm import Session

from src.data.models import Order, TradeOutcome
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
        # Already recorded sell_order_ids
        recorded = {row[0] for row in session.query(TradeOutcome.sell_order_id).all()}

        # Filled or dry_run SELL/REDUCE orders not yet recorded
        sell_orders = (
            session.query(Order)
            .filter(
                Order.action.in_(["SELL", "REDUCE"]),
                Order.status.in_(["filled", "dry_run"]),
                Order.id.notin_(recorded) if recorded else True,
            )
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


def _match_sell_to_buys(session: Session, sell_order: Order) -> TradeOutcome | None:
    """Match one SELL/REDUCE order to prior BUYs (FIFO), compute P&L and return one TradeOutcome."""
    ticker = sell_order.ticker
    sell_qty = abs(float(sell_order.quantity))
    sell_value = float(sell_order.value_gbp or 0)
    sell_ts = sell_order.timestamp

    if sell_qty <= 0:
        return None

    # BUY orders for this ticker, filled/dry_run, chronological
    buys = (
        session.query(Order)
        .filter(
            Order.ticker == ticker,
            Order.action == "BUY",
            Order.status.in_(["filled", "dry_run"]),
            Order.timestamp < sell_ts,
        )
        .order_by(Order.timestamp.asc())
        .all()
    )

    # FIFO: consume buy quantities until we've covered sell_qty
    remaining = sell_qty
    buy_value_total = 0.0
    first_buy: Order | None = None
    first_buy_ts = None

    for buy in buys:
        if remaining <= 0:
            break
        buy_qty = float(buy.quantity)
        buy_value = float(buy.value_gbp or 0)
        if buy_qty <= 0:
            continue
        if first_buy is None:
            first_buy = buy
            first_buy_ts = buy.timestamp
        take = min(remaining, buy_qty)
        proportion = take / buy_qty
        buy_value_total += buy_value * proportion
        remaining -= take

    if remaining > 0.01:
        # Sell quantity not fully matched (e.g. manual or external buy)
        logger.debug(f"Trade outcome: sell {ticker} qty {sell_qty} only matched {sell_qty - remaining:.2f} from BUYs")
        if buy_value_total <= 0:
            return None
        # Use sell value proportionally for matched portion
        sell_value = sell_value * (sell_qty - remaining) / sell_qty if sell_qty else 0

    if buy_value_total <= 0:
        return None

    pnl_gbp = sell_value - buy_value_total
    pnl_pct = (pnl_gbp / buy_value_total * 100) if buy_value_total else 0
    holding_days = (sell_ts - first_buy_ts).total_seconds() / 86400.0 if first_buy_ts else None

    return TradeOutcome(
        buy_order_id=first_buy.id if first_buy else None,
        sell_order_id=sell_order.id,
        ticker=ticker,
        buy_timestamp=first_buy_ts,
        sell_timestamp=sell_ts,
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
