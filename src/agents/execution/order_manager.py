"""Order management with deduplication and execution logic."""

import json
from datetime import datetime, timedelta
from typing import Any

from src.agents.execution.t212_client import T212Client, calculate_quantity
from src.data.database import get_session
from src.data.models import Order
from src.utils.logger import get_logger

logger = get_logger("order_manager")

DEDUP_WINDOW_MINUTES = 5


class OrderManager:
    """Manages order execution with deduplication and logging."""

    def __init__(self, client: T212Client | None = None, dry_run: bool = False) -> None:
        self.client = client or T212Client()
        self.dry_run = dry_run

    def _make_dedup_key(self, ticker: str, quantity: float) -> str:
        """Create a deduplication key: ticker_direction_absqty."""
        direction = "BUY" if quantity > 0 else "SELL"
        return f"{ticker}_{direction}_{abs(quantity):.2f}"

    def _is_duplicate(self, dedup_key: str) -> bool:
        """Check if a similar order was placed within the dedup window."""
        session = get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(minutes=DEDUP_WINDOW_MINUTES)
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
                timestamp=datetime.utcnow(),
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
            action: BUY or SELL
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

        if action == "SELL":
            quantity = -quantity

        dedup_key = self._make_dedup_key(ticker, quantity)

        if self._is_duplicate(dedup_key):
            logger.warning(f"Duplicate order detected: {dedup_key}")
            return {"status": "skipped", "reason": "duplicate"}

        value_gbp = abs(quantity) * current_price

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
            result = self.client.place_market_order(ticker, quantity)
            t212_order_id = result.get("id") or result.get("orderId")

            order = self._log_order(
                ticker=ticker,
                action=action,
                order_type="market",
                quantity=quantity,
                price=current_price,
                value_gbp=value_gbp,
                t212_order_id=str(t212_order_id) if t212_order_id else None,
                status="filled",
                strategy=strategy,
                conviction=conviction,
                moderation_result=moderation_result,
                risk_result=risk_result,
                dedup_key=dedup_key,
            )

            logger.info(f"Order executed: {action} {abs(quantity)} x {ticker} = £{value_gbp:.2f}")
            return {
                "status": "filled",
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

    def get_portfolio_state(self) -> dict[str, Any]:
        """Get current portfolio positions and cash."""
        try:
            cash_data = self.client.get_cash()
            portfolio = self.client.get_portfolio()
            return {
                "cash": cash_data,
                "positions": portfolio,
                "num_positions": len(portfolio),
            }
        except Exception as e:
            logger.error(f"Failed to get portfolio state: {e}")
            return {"cash": {}, "positions": [], "num_positions": 0, "error": str(e)}

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
