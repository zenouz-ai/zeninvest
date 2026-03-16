"""Order management with deduplication and execution logic."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from src.agents.execution.t212_client import T212Client, calculate_quantity
from src.data.database import get_session
from src.data.models import Order
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("order_manager")

# Dashboard event logger (fail-open import)
log_event: Callable[..., None] | None
try:
    from dashboard.backend.app.services.event_logger import log_event as _log_event
    log_event = _log_event
    DASHBOARD_AVAILABLE = True
except ImportError:
    DASHBOARD_AVAILABLE = False
    log_event = None

DEDUP_WINDOW_MINUTES = 5


class OrderManager:
    """Manages order execution with deduplication and logging."""

    def __init__(self, client: T212Client | None = None, dry_run: bool = False) -> None:
        self.client = client or T212Client()
        self.dry_run = dry_run
        self.settings = get_settings()

    def _passes_min_order_value(
        self,
        *,
        action: str,
        order_type: str,
        value_gbp: float,
        allow_below_min_full_sell: bool = False,
    ) -> tuple[bool, str | None]:
        """Validate minimum order value policy before executing/logging."""
        min_order = float(self.settings.min_order_value_gbp)
        if value_gbp >= min_order:
            return True, None
        if allow_below_min_full_sell and action == "SELL" and order_type == "market":
            return True, None
        return False, "below_min_order_value"

    def _make_dedup_key(self, ticker: str, quantity: float) -> str:
        """Create a deduplication key: ticker_direction_absqty."""
        direction = "BUY" if quantity > 0 else "SELL"
        return f"{ticker}_{direction}_{abs(quantity):.2f}"

    def _is_duplicate(self, dedup_key: str) -> bool:
        """Check if a similar order was placed within the dedup window."""
        session = get_session()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=DEDUP_WINDOW_MINUTES)
            exists = (
                session.query(Order)
                .filter(
                    Order.dedup_key == dedup_key,
                    Order.timestamp >= cutoff,
                    Order.status.in_(["pending", "filled", "dry_run"]),
                )
                .first()
            )
            return exists is not None
        finally:
            session.close()

    def _log_order(
        self,
        ticker: str,
        action: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        limit_price: float | None = None,
        stop_price: float | None = None,
        value_gbp: float | None = None,
        t212_order_id: str | None = None,
        status: str = "pending",
        strategy: str | None = None,
        conviction: int | None = None,
        moderation_result: str | None = None,
        risk_result: str | None = None,
        error_message: str | None = None,
        dedup_key: str | None = None,
    ) -> Order:
        """Log an order to the database."""
        session = get_session()
        try:
            order = Order(
                timestamp=datetime.now(timezone.utc),
                ticker=ticker,
                action=action,
                order_type=order_type,
                quantity=quantity,
                price=price,
                limit_price=limit_price,
                stop_price=stop_price,
                value_gbp=value_gbp,
                t212_order_id=t212_order_id,
                status=status,
                strategy=strategy,
                conviction=conviction,
                moderation_result=moderation_result,
                risk_result=risk_result,
                error_message=error_message,
                dedup_key=dedup_key,
            )
            session.add(order)
            session.commit()
            session.refresh(order)
            return order
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def execute_market_order(
        self,
        ticker: str,
        action: str,
        target_amount_gbp: float,
        current_price: float,
        strategy: str | None = None,
        conviction: int | None = None,
        moderation_result: str | None = None,
        risk_result: str | None = None,
    ) -> dict[str, Any]:
        """Execute a market order with deduplication.

        Args:
            ticker: Instrument ticker (e.g., "AAPL_US_EQ")
            action: BUY, SELL, or REDUCE
            target_amount_gbp: Target trade value in GBP
            current_price: Current market price
            strategy: Which strategy triggered this
            conviction: Conviction score
            moderation_result: Moderation panel result
            risk_result: Risk agent result
        """
        quantity = calculate_quantity(target_amount_gbp, current_price)
        if quantity <= 0:
            logger.warning(f"Calculated quantity is 0 for {ticker} @ {current_price}")
            return {"status": "skipped", "reason": "zero_quantity"}

        if action in ("SELL", "REDUCE"):
            quantity = -quantity

        dedup_key = self._make_dedup_key(ticker, quantity)

        if self._is_duplicate(dedup_key):
            logger.warning(f"Duplicate order detected: {dedup_key}")
            return {"status": "skipped", "reason": "duplicate"}

        value_gbp = abs(quantity) * current_price
        can_place, reject_reason = self._passes_min_order_value(
            action=action,
            order_type="market",
            value_gbp=value_gbp,
            allow_below_min_full_sell=True,
        )
        if not can_place:
            logger.info(
                f"Order skipped: {action} {ticker} value £{value_gbp:.2f} below minimum "
                f"£{self.settings.min_order_value_gbp:.2f}"
            )
            return {"status": "skipped", "reason": reject_reason}

        if self.dry_run:
            logger.info(f"[DRY RUN] Would execute: {action} {abs(quantity)} x {ticker} @ {current_price}")
            order = self._log_order(
                ticker=ticker,
                action=action,
                order_type="market",
                quantity=quantity,
                price=current_price,
                value_gbp=value_gbp,
                status="dry_run",
                strategy=strategy,
                conviction=conviction,
                moderation_result=moderation_result,
                risk_result=risk_result,
                dedup_key=dedup_key,
            )
            
            # Log order_placed event
            if DASHBOARD_AVAILABLE and log_event is not None:
                try:
                    log_event(
                        event_type="order_placed",
                        source="execution",
                        message=f"[DRY RUN] {action} {abs(quantity)} x {ticker} @ {current_price}",
                        metadata={
                            "order_id": order.id,
                            "ticker": ticker,
                            "action": action,
                            "quantity": abs(quantity),
                            "price": current_price,
                            "value_gbp": value_gbp,
                            "status": "dry_run",
                            "strategy": strategy,
                            "conviction": conviction,
                        },
                    )
                except Exception:
                    pass  # Fail-open
            
            return {
                "status": "dry_run",
                "order_id": order.id,
                "ticker": ticker,
                "action": action,
                "quantity": abs(quantity),
                "price": current_price,
                "value_gbp": value_gbp,
            }

        try:
            # Log order_placed event before execution
            if DASHBOARD_AVAILABLE and log_event is not None:
                try:
                    log_event(
                        event_type="order_placed",
                        source="execution",
                        message=f"Placing {action} order: {abs(quantity)} x {ticker} @ {current_price}",
                        metadata={
                            "ticker": ticker,
                            "action": action,
                            "quantity": abs(quantity),
                            "price": current_price,
                            "value_gbp": value_gbp,
                            "strategy": strategy,
                            "conviction": conviction,
                        },
                    )
                except Exception:
                    pass  # Fail-open
            
            result = self.client.place_market_order(ticker, quantity)
            t212_order_id = result.get("id") or result.get("orderId")
            t212_status = (result.get("status") or "").upper()

            # Map T212 status to our DB status (do not assume filled — T212 may return NEW/pending)
            if t212_status in ("FILLED", "PARTIALLY_FILLED"):
                db_status = "filled"
            elif t212_status in ("REJECTED", "CANCELLED", "CANCELLING"):
                db_status = "failed"
                logger.warning(f"T212 order {t212_order_id} status={t212_status}")
            else:
                db_status = "pending"
                if t212_status and t212_status not in ("NEW", "CONFIRMED", "UNCONFIRMED", "LOCAL"):
                    logger.info(f"T212 order {t212_order_id} status={t212_status} -> pending")

            order = self._log_order(
                ticker=ticker,
                action=action,
                order_type="market",
                quantity=quantity,
                price=current_price,
                value_gbp=value_gbp,
                t212_order_id=str(t212_order_id) if t212_order_id else None,
                status=db_status,
                strategy=strategy,
                conviction=conviction,
                moderation_result=moderation_result,
                risk_result=risk_result,
                dedup_key=dedup_key,
            )

            logger.info(
                f"Order {'filled' if db_status == 'filled' else 'placed'}: {action} {abs(quantity)} x {ticker} = £{value_gbp:.2f} (T212 status={t212_status})"
            )

            # Log order_executed event (or order_placed for pending)
            if DASHBOARD_AVAILABLE and log_event is not None:
                try:
                    log_event(
                        event_type="order_executed",
                        source="execution",
                        message=f"Order {db_status}: {action} {abs(quantity)} x {ticker} @ {current_price} = £{value_gbp:.2f}",
                        metadata={
                            "order_id": order.id,
                            "t212_order_id": str(t212_order_id) if t212_order_id else None,
                            "ticker": ticker,
                            "action": action,
                            "quantity": abs(quantity),
                            "price": current_price,
                            "value_gbp": value_gbp,
                            "status": db_status,
                            "t212_status": t212_status,
                            "strategy": strategy,
                            "conviction": conviction,
                        },
                    )
                except Exception:
                    pass  # Fail-open

            return {
                "status": db_status,
                "order_id": order.id,
                "t212_order_id": t212_order_id,
                "ticker": ticker,
                "action": action,
                "quantity": abs(quantity),
                "price": current_price,
                "value_gbp": value_gbp,
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Order failed for {ticker}: {error_msg}")
            self._log_order(
                ticker=ticker,
                action=action,
                order_type="market",
                quantity=quantity,
                price=current_price,
                value_gbp=value_gbp,
                status="failed",
                strategy=strategy,
                conviction=conviction,
                error_message=error_msg,
                dedup_key=dedup_key,
            )
            return {"status": "failed", "error": error_msg}

    def sync_order_status_from_t212(self) -> int:
        """Sync pending orders with T212 order history. Updates local Order.status to filled when T212 reports FILLED.

        Returns:
            Number of orders updated.
        """
        if self.dry_run:
            return 0
        try:
            updated = 0
            cursor: str | None = None
            t212_ids_seen: set[str] = set()

            while True:
                resp = self.client.get_order_history(cursor=cursor, limit=50)
                items = resp.get("items") or []
                next_page = resp.get("nextPagePath")

                for item in items:
                    order_obj = item.get("order") if isinstance(item, dict) else None
                    if not order_obj:
                        continue
                    t212_id = str(order_obj.get("id") or order_obj.get("orderId") or "")
                    if not t212_id or t212_id in t212_ids_seen:
                        continue
                    t212_ids_seen.add(t212_id)
                    t212_status = (order_obj.get("status") or "").upper()

                    if t212_status not in ("FILLED", "PARTIALLY_FILLED"):
                        continue

                    session = get_session()
                    try:
                        row = (
                            session.query(Order)
                            .filter(Order.t212_order_id == t212_id, Order.status == "pending")
                            .first()
                        )
                        if row:
                            row.status = "filled"
                            filled_qty = order_obj.get("filledQuantity")
                            filled_val = order_obj.get("filledValue")
                            if filled_qty is not None and filled_qty > 0 and row.price is None:
                                row.price = (filled_val or 0) / filled_qty if filled_val else None
                            session.commit()
                            updated += 1
                            logger.info(f"Order {t212_id} synced to filled")
                    except Exception as e:
                        logger.warning(f"Failed to sync order {t212_id}: {e}")
                        session.rollback()
                    finally:
                        session.close()

                if not next_page or len(items) < 50:
                    break
                cursor = next_page

            if updated:
                logger.info(f"Order sync: {updated} pending orders updated to filled")
            return updated
        except Exception as e:
            logger.warning(f"Order status sync failed: {e}")
            return 0

    def get_portfolio_state(self) -> dict[str, Any]:
        """Get current portfolio positions and cash.

        Fetches account summary when available; totalValue from summary is the
        authoritative total (cash + investments + reserved) for drawdown logic.
        """
        try:
            cash_data = self.client.get_cash()
            portfolio = self.client.get_portfolio()
            summary: dict[str, Any] = {}
            try:
                summary = self.client.get_account_summary()
            except Exception as e:
                logger.debug(f"Account summary unavailable, using cash+portfolio: {e}")
            return {
                "cash": cash_data,
                "positions": portfolio,
                "num_positions": len(portfolio),
                "account_summary": summary,
            }
        except Exception as e:
            logger.error(f"Failed to get portfolio state: {e}")
            return {"cash": {}, "positions": [], "num_positions": 0, "account_summary": {}, "error": str(e)}

    def place_stop_loss(
        self,
        ticker: str,
        quantity: float,
        current_price: float,
        stop_loss_pct: float,
        strategy: str | None = None,
    ) -> dict[str, Any]:
        """Place a stop-loss order for a position.

        Args:
            ticker: Instrument ticker (e.g., "AAPL_US_EQ")
            quantity: Number of shares to protect (positive).
            current_price: Current market price.
            stop_loss_pct: Negative percentage (e.g., -8.0 for 8% below).
            strategy: Which strategy triggered this.

        Returns:
            Result dict with order status.
        """
        if stop_loss_pct >= 0 or quantity <= 0:
            return {"status": "skipped", "reason": "invalid_stop_loss_params"}

        stop_price = round(current_price * (1 + stop_loss_pct / 100), 2)
        sell_quantity = -quantity  # Negative for sell
        stop_order_value = abs(sell_quantity) * current_price
        can_place, reject_reason = self._passes_min_order_value(
            action="SELL",
            order_type="stop",
            value_gbp=stop_order_value,
            allow_below_min_full_sell=False,
        )
        if not can_place:
            logger.info(
                f"Stop-loss skipped: {ticker} value £{stop_order_value:.2f} below minimum "
                f"£{self.settings.min_order_value_gbp:.2f}"
            )
            return {"status": "skipped", "order_type": "stop", "reason": reject_reason}

        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would place stop-loss: SELL {quantity} x {ticker} "
                f"@ stop={stop_price} (current={current_price}, pct={stop_loss_pct}%)"
            )
            order = self._log_order(
                ticker=ticker,
                action="SELL",
                order_type="stop",
                quantity=sell_quantity,
                stop_price=stop_price,
                price=current_price,
                value_gbp=stop_order_value,
                status="dry_run",
                strategy=strategy,
            )
            return {
                "status": "dry_run",
                "order_type": "stop",
                "order_id": order.id,
                "ticker": ticker,
                "stop_price": stop_price,
                "quantity": quantity,
            }

        try:
            result = self.client.place_stop_order(
                ticker=ticker,
                quantity=sell_quantity,
                stop_price=stop_price,
                time_validity="GTC",
            )
            t212_order_id = result.get("id") or result.get("orderId")

            order = self._log_order(
                ticker=ticker,
                action="SELL",
                order_type="stop",
                quantity=sell_quantity,
                stop_price=stop_price,
                price=current_price,
                value_gbp=stop_order_value,
                t212_order_id=str(t212_order_id) if t212_order_id else None,
                status="pending",
                strategy=strategy,
            )

            logger.info(
                f"Stop-loss placed: SELL {quantity} x {ticker} "
                f"@ stop={stop_price} (order_id={t212_order_id})"
            )
            return {
                "status": "placed",
                "order_type": "stop",
                "order_id": order.id,
                "t212_order_id": t212_order_id,
                "ticker": ticker,
                "stop_price": stop_price,
                "quantity": quantity,
            }
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Stop-loss order failed for {ticker}: {error_msg}")
            self._log_order(
                ticker=ticker,
                action="SELL",
                order_type="stop",
                quantity=sell_quantity,
                stop_price=stop_price,
                value_gbp=stop_order_value,
                status="failed",
                strategy=strategy,
                error_message=error_msg,
            )
            return {"status": "failed", "order_type": "stop", "error": error_msg}

    def liquidate_all(self) -> list[dict[str, Any]]:
        """Sell all positions (for HALTED state)."""
        results = []
        try:
            portfolio = self.client.get_portfolio()
            for position in portfolio:
                ticker = position.get("ticker", "")
                quantity = float(position.get("quantity", 0))
                if quantity > 0:
                    try:
                        result = self.client.place_market_order(ticker, -quantity)
                        self._log_order(
                            ticker=ticker,
                            action="SELL",
                            order_type="market",
                            quantity=-quantity,
                            status="filled",
                            strategy="liquidation",
                        )
                        results.append({"ticker": ticker, "status": "sold", "result": result})
                        logger.info(f"Liquidated {quantity} x {ticker}")
                    except Exception as e:
                        results.append({"ticker": ticker, "status": "failed", "error": str(e)})
                        logger.error(f"Failed to liquidate {ticker}: {e}")
        except Exception as e:
            logger.error(f"Failed to get portfolio for liquidation: {e}")
            results.append({"status": "error", "error": str(e)})
        return results

    def close(self) -> None:
        """Close the underlying client."""
        self.client.close()
