"""Intelligent stop-loss management: reassessment, trailing stops, and limit orders.

Since Trading 212 does not support native trailing stops or order modification,
this module implements software-based equivalents by cancelling and replacing
stop orders each cycle.
"""

from datetime import datetime, timezone
from typing import Any

from src.agents.execution.order_manager import OrderManager
from src.agents.execution.t212_client import T212Client
from src.data.database import get_session
from src.data.models import Order, StopLossAdjustment
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("stop_loss_manager")


class StopLossManager:
    """Manages stop-loss lifecycle: reassessment, trailing ratchets, and limit orders."""

    def __init__(
        self,
        order_manager: OrderManager,
        client: T212Client | None = None,
        dry_run: bool = False,
    ) -> None:
        self.order_manager = order_manager
        self.client = client or order_manager.client
        self.dry_run = dry_run
        self.settings = get_settings()

    def reassess_stops(
        self,
        positions: list[dict[str, Any]],
        stocks_data: list[dict[str, Any]],
        cycle_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Reassess stop-losses for all held positions based on current ATR.

        For each position:
        1. Look up its existing pending stop order (from T212 or DB).
        2. Compute a new volatility-based stop level: price - (ATR * multiplier).
        3. Clamp to [min_stop_distance_pct, max_stop_distance_pct].
        4. If only_tighten_stops is True, only move stop *up* (tighter).
        5. Cancel old stop and place new one if the level changed materially.

        Returns a list of adjustment result dicts.
        """
        if not self.settings.reassess_stops_enabled:
            return []

        data_by_ticker = {s.get("ticker", ""): s for s in stocks_data}
        pending_stops = self._get_pending_stops()
        results: list[dict[str, Any]] = []

        for pos in positions:
            ticker = (pos.get("instrument") or {}).get("ticker") or pos.get("ticker", "")
            quantity = float(pos.get("quantity", 0))
            current_price = float(pos.get("currentPrice", 0))
            if not ticker or quantity <= 0 or current_price <= 0:
                continue

            stock = data_by_ticker.get(ticker, {})
            atr = self._extract_atr(stock)
            if atr is None or atr <= 0:
                logger.debug(f"No ATR for {ticker}, skipping reassessment")
                continue

            new_stop = self._compute_volatility_stop(current_price, atr)
            old_stop_info = pending_stops.get(ticker)
            old_stop_price = float(old_stop_info["stopPrice"]) if old_stop_info else None

            # Only tighten: skip if new stop is lower than existing
            if (
                self.settings.only_tighten_stops
                and old_stop_price is not None
                and new_stop <= old_stop_price
            ):
                logger.debug(
                    f"{ticker}: new stop {new_stop:.2f} <= existing {old_stop_price:.2f}, skipping (only_tighten)"
                )
                continue

            # Skip if change is negligible (< 0.5%)
            if old_stop_price and abs(new_stop - old_stop_price) / old_stop_price < 0.005:
                continue

            result = self._replace_stop(
                ticker=ticker,
                quantity=quantity,
                new_stop_price=new_stop,
                current_price=current_price,
                old_stop_info=old_stop_info,
                adjustment_type="reassess",
                trigger_reason="volatility_adjust",
                atr_value=atr,
                cycle_id=cycle_id,
            )
            results.append(result)

        return results

    def place_missing_stops(
        self,
        positions: list[dict[str, Any]],
        stocks_data: list[dict[str, Any]],
        cycle_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Place stop-loss for positions that have none.

        For each position without a pending stop, place one using default_stop_loss_pct
        (or ATR-based if available and reassess_stops would use it).
        """
        if not self.settings.order_management_enabled:
            return []

        pending_stops = self._get_pending_stops()
        data_by_ticker = {s.get("ticker", ""): s for s in stocks_data}
        results: list[dict[str, Any]] = []

        for pos in positions:
            ticker = (pos.get("instrument") or {}).get("ticker") or pos.get("ticker", "")
            quantity = float(pos.get("quantity", 0))
            current_price = float(pos.get("currentPrice", 0))
            if not ticker or quantity <= 0 or current_price <= 0:
                continue
            if ticker in pending_stops:
                continue

            stock = data_by_ticker.get(ticker, {})
            atr = self._extract_atr(stock)
            if atr is not None and atr > 0 and self.settings.reassess_stops_enabled:
                new_stop = self._compute_volatility_stop(current_price, atr)
                stop_loss_pct = -((current_price - new_stop) / current_price * 100)
            else:
                stop_loss_pct = self.settings.default_stop_loss_pct
                new_stop = round(current_price * (1 + stop_loss_pct / 100), 2)

            if stop_loss_pct >= 0:
                logger.debug(f"{ticker}: invalid stop_loss_pct {stop_loss_pct}, skipping")
                continue

            result = self._replace_stop(
                ticker=ticker,
                quantity=quantity,
                new_stop_price=new_stop,
                current_price=current_price,
                old_stop_info=None,
                adjustment_type="place_missing",
                trigger_reason="no_stop",
                atr_value=atr,
                cycle_id=cycle_id,
            )
            results.append(result)
            logger.info(f"Placed missing stop for {ticker} @ {new_stop}")

        return results

    def apply_trailing_stops(
        self,
        positions: list[dict[str, Any]],
        cycle_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Apply trailing stop logic: ratchet stops up as price makes new highs.

        Uses a high-water mark (HWM) tracked via the most recent StopLossAdjustment
        for each ticker. The stop is set at HWM * (1 - trail_pct/100).
        """
        if not self.settings.trailing_stops_enabled:
            return []

        trail_pct = self.settings.trailing_stop_default_trail_pct
        pending_stops = self._get_pending_stops()
        results: list[dict[str, Any]] = []

        min_profit_pct = float(
            self.settings._config.get("order_management", {})
            .get("trailing_stops", {})
            .get("min_profit_pct", 0)
        )

        for pos in positions:
            ticker = (pos.get("instrument") or {}).get("ticker") or pos.get("ticker", "")
            quantity = float(pos.get("quantity", 0))
            current_price = float(pos.get("currentPrice", 0))
            if not ticker or quantity <= 0 or current_price <= 0:
                continue

            if min_profit_pct > 0:
                wallet = pos.get("walletImpact") or {}
                total_cost = float(wallet.get("totalCost", 0))
                if total_cost > 0:
                    unrealised = float(wallet.get("unrealizedProfitLoss", 0))
                    pnl_pct = (unrealised / total_cost) * 100
                    if pnl_pct < min_profit_pct:
                        continue

            # Get last known HWM from DB
            prev_hwm = self._get_last_hwm(ticker)
            hwm = max(current_price, prev_hwm) if prev_hwm else current_price

            new_stop = round(hwm * (1 - trail_pct / 100), 2)
            old_stop_info = pending_stops.get(ticker)
            old_stop_price = float(old_stop_info["stopPrice"]) if old_stop_info else None

            # Guard: trailing stop must remain below current price
            if new_stop >= current_price:
                logger.warning(
                    f"Trailing ratchet skipped for {ticker}: computed stop {new_stop} >= "
                    f"current_price {current_price} (price may have fallen below HWM-stop level)"
                )
                self._record_adjustment(
                    ticker=ticker,
                    adjustment_type="trailing",
                    old_stop_price=old_stop_price,
                    new_stop_price=new_stop,
                    current_price=current_price,
                    high_water_mark=hwm,
                    trigger_reason="trailing_ratchet_invalid",
                    status="skipped",
                    cycle_id=cycle_id,
                )
                continue

            # Only move stop up
            if old_stop_price is not None and new_stop <= old_stop_price:
                # Still record HWM update even if stop doesn't move
                if hwm > (prev_hwm or 0):
                    self._record_adjustment(
                        ticker=ticker,
                        adjustment_type="trailing",
                        old_stop_price=old_stop_price,
                        new_stop_price=old_stop_price,  # unchanged
                        current_price=current_price,
                        high_water_mark=hwm,
                        trigger_reason="hwm_update_no_ratchet",
                        status="skipped",
                        cycle_id=cycle_id,
                    )
                continue

            result = self._replace_stop(
                ticker=ticker,
                quantity=quantity,
                new_stop_price=new_stop,
                current_price=current_price,
                old_stop_info=old_stop_info,
                adjustment_type="trailing",
                trigger_reason="trailing_ratchet",
                high_water_mark=hwm,
                cycle_id=cycle_id,
            )
            results.append(result)

        return results

    def place_limit_buy(
        self,
        ticker: str,
        target_amount_gbp: float,
        current_price: float,
        offset_pct: float | None = None,
        strategy: str | None = None,
        conviction: int | None = None,
        cycle_id: str | None = None,
    ) -> dict[str, Any]:
        """Place a limit BUY order below the current price for dip-buying.

        Args:
            ticker: Instrument ticker.
            target_amount_gbp: Target trade value.
            current_price: Current market price.
            offset_pct: % below current price for limit. Uses config default if None.
            strategy: Strategy name for audit.
            conviction: Conviction score.
            cycle_id: Cycle identifier.
        """
        if not self.settings.limit_orders_enabled:
            return {"status": "skipped", "reason": "limit_orders_disabled"}

        pct = offset_pct or self.settings.limit_order_default_offset_pct
        limit_price = round(current_price * (1 - pct / 100), 2)
        validity = self.settings.limit_order_time_validity

        from src.agents.execution.t212_client import calculate_quantity

        quantity = calculate_quantity(target_amount_gbp, limit_price)
        if quantity <= 0:
            return {"status": "skipped", "reason": "zero_quantity"}
        order_value = quantity * limit_price
        can_place, reject_reason = self.order_manager._passes_min_order_value(
            action="BUY",
            order_type="limit",
            value_gbp=order_value,
            allow_below_min_full_sell=False,
        )
        if not can_place:
            logger.info(
                f"Limit BUY skipped: {ticker} value £{order_value:.2f} below minimum "
                f"£{self.settings.min_order_value_gbp:.2f}"
            )
            return {"status": "skipped", "order_type": "limit", "reason": reject_reason}

        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would place limit BUY: {quantity} x {ticker} "
                f"@ limit={limit_price} (current={current_price}, offset={pct}%)"
            )
            order = self.order_manager._log_order(
                ticker=ticker,
                action="BUY",
                order_type="limit",
                quantity=quantity,
                limit_price=limit_price,
                price=current_price,
                value_gbp=order_value,
                status="dry_run",
                strategy=strategy,
                conviction=conviction,
            )
            self._record_adjustment(
                ticker=ticker,
                adjustment_type="limit_order",
                new_stop_price=limit_price,
                current_price=current_price,
                trigger_reason="limit_dip",
                status="dry_run",
                cycle_id=cycle_id,
            )
            return {
                "status": "dry_run",
                "order_type": "limit",
                "order_id": order.id,
                "ticker": ticker,
                "limit_price": limit_price,
                "quantity": quantity,
            }

        try:
            result = self.client.place_limit_order(
                ticker=ticker,
                quantity=quantity,
                limit_price=limit_price,
                time_validity=validity,
            )
            t212_order_id = result.get("id") or result.get("orderId")

            order = self.order_manager._log_order(
                ticker=ticker,
                action="BUY",
                order_type="limit",
                quantity=quantity,
                limit_price=limit_price,
                price=current_price,
                value_gbp=order_value,
                t212_order_id=str(t212_order_id) if t212_order_id else None,
                status="pending",
                strategy=strategy,
                conviction=conviction,
            )
            self._record_adjustment(
                ticker=ticker,
                adjustment_type="limit_order",
                new_stop_price=limit_price,
                current_price=current_price,
                trigger_reason="limit_dip",
                t212_new_order_id=str(t212_order_id) if t212_order_id else None,
                status="placed",
                cycle_id=cycle_id,
            )
            logger.info(
                f"Limit BUY placed: {quantity} x {ticker} @ {limit_price} "
                f"(order_id={t212_order_id})"
            )
            return {
                "status": "placed",
                "order_type": "limit",
                "order_id": order.id,
                "t212_order_id": t212_order_id,
                "ticker": ticker,
                "limit_price": limit_price,
                "quantity": quantity,
            }
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Limit BUY failed for {ticker}: {error_msg}")
            self.order_manager._log_order(
                ticker=ticker,
                action="BUY",
                order_type="limit",
                quantity=quantity,
                limit_price=limit_price,
                value_gbp=order_value,
                status="failed",
                strategy=strategy,
                error_message=error_msg,
            )
            self._record_adjustment(
                ticker=ticker,
                adjustment_type="limit_order",
                new_stop_price=limit_price,
                current_price=current_price,
                trigger_reason="limit_dip",
                status="failed",
                cycle_id=cycle_id,
            )
            return {"status": "failed", "order_type": "limit", "error": error_msg}

    # --- Internal helpers ---

    def _compute_volatility_stop(self, current_price: float, atr: float) -> float:
        """Compute stop price using ATR, clamped to configured bounds."""
        raw_distance = atr * self.settings.atr_multiplier
        raw_pct = (raw_distance / current_price) * 100

        clamped_pct = max(
            self.settings.min_stop_distance_pct,
            min(raw_pct, self.settings.max_stop_distance_pct),
        )
        return round(current_price * (1 - clamped_pct / 100), 2)

    def _replace_stop(
        self,
        ticker: str,
        quantity: float,
        new_stop_price: float,
        current_price: float,
        old_stop_info: dict[str, Any] | None,
        adjustment_type: str,
        trigger_reason: str,
        atr_value: float | None = None,
        high_water_mark: float | None = None,
        cycle_id: str | None = None,
    ) -> dict[str, Any]:
        """Cancel old stop first, then place new stop with emergency fallback.

        T212 only allows one pending stop per instrument at a time, so the old stop
        must be cancelled before placing the new one. If the new stop fails, an
        emergency fallback stop is re-placed at the old price to keep protection.
        """
        old_stop_price = float(old_stop_info["stopPrice"]) if old_stop_info else None
        cancelled_order_id = None

        # Cancel old stop FIRST — T212 only allows one pending stop per instrument.
        # Accept a brief unprotected window (milliseconds) as the lesser risk vs.
        # infinite ratchet failures from T212 rejecting two concurrent stops.
        if old_stop_info and not self.dry_run:
            old_order_id = old_stop_info.get("id") or old_stop_info.get("orderId")
            if old_order_id:
                try:
                    self.client.cancel_order(str(old_order_id))
                    cancelled_order_id = str(old_order_id)
                    logger.info(f"Cancelled old stop for {ticker}: order_id={old_order_id}")
                except Exception as e:
                    logger.warning(
                        f"Could not cancel old stop for {ticker} before ratchet: {e}. "
                        f"Attempting new stop placement anyway."
                    )

        # Place new stop
        stop_result = self.order_manager.place_stop_loss(
            ticker=ticker,
            quantity=quantity,
            current_price=current_price,
            stop_loss_pct=-((current_price - new_stop_price) / current_price * 100),
            strategy="order_management",
        )

        new_order_id = stop_result.get("t212_order_id")
        status = stop_result.get("status", "failed")

        # Emergency fallback: if new stop failed AND old stop was cancelled, re-place at old price
        if status == "failed" and cancelled_order_id and old_stop_price:
            logger.warning(
                f"New stop at {new_stop_price} failed for {ticker} — "
                f"re-placing emergency stop at old price {old_stop_price}"
            )
            fallback_pct = -((current_price - old_stop_price) / current_price * 100)
            fallback_result = self.order_manager.place_stop_loss(
                ticker=ticker,
                quantity=quantity,
                current_price=current_price,
                stop_loss_pct=fallback_pct,
                strategy="order_management",
            )
            fallback_status = fallback_result.get("status", "failed")
            if fallback_status in ("placed", "pending"):
                logger.info(f"Emergency fallback stop placed at {old_stop_price} for {ticker}")
            else:
                logger.error(
                    f"Emergency fallback stop also failed for {ticker} — "
                    f"position is now unprotected!"
                )

        self._record_adjustment(
            ticker=ticker,
            adjustment_type=adjustment_type,
            old_stop_price=old_stop_price,
            new_stop_price=new_stop_price,
            current_price=current_price,
            high_water_mark=high_water_mark,
            atr_value=atr_value,
            trigger_reason=trigger_reason,
            t212_cancelled_order_id=cancelled_order_id,
            t212_new_order_id=str(new_order_id) if new_order_id else None,
            status=status,
            cycle_id=cycle_id,
        )

        logger.info(
            f"Stop {adjustment_type} for {ticker}: "
            f"{old_stop_price} -> {new_stop_price} (current={current_price}, status={status})"
        )

        return {
            "ticker": ticker,
            "adjustment_type": adjustment_type,
            "old_stop_price": old_stop_price,
            "new_stop_price": new_stop_price,
            "current_price": current_price,
            "high_water_mark": high_water_mark,
            "atr": atr_value,
            "trigger_reason": trigger_reason,
            "status": status,
        }

    def _get_pending_stops(self) -> dict[str, dict[str, Any]]:
        """Get all pending stop orders from T212, keyed by ticker."""
        if self.dry_run:
            return self._get_pending_stops_from_db()
        try:
            pending = self.client.get_pending_orders()
            stops: dict[str, dict[str, Any]] = {}
            for order in pending:
                if order.get("type") == "STOP" or "stopPrice" in order:
                    t = order.get("ticker", "")
                    if t:
                        stops[t] = order
            return stops
        except Exception as e:
            logger.warning(f"Failed to fetch pending orders from T212: {e}")
            return self._get_pending_stops_from_db()

    def _get_pending_stops_from_db(self) -> dict[str, dict[str, Any]]:
        """Fallback: get pending stop orders from local DB."""
        session = get_session()
        try:
            rows = (
                session.query(Order)
                .filter(
                    Order.order_type == "stop",
                    Order.status.in_(["pending", "dry_run"]),
                )
                .all()
            )
            stops: dict[str, dict[str, Any]] = {}
            for row in rows:
                stops[str(row.ticker)] = {
                    "ticker": row.ticker,
                    "stopPrice": row.stop_price,
                    "id": row.t212_order_id,
                    "quantity": abs(row.quantity),
                }
            return stops
        finally:
            session.close()

    def _get_last_hwm(self, ticker: str) -> float | None:
        """Get the last recorded high-water mark for trailing stop."""
        session = get_session()
        try:
            row = (
                session.query(StopLossAdjustment)
                .filter(
                    StopLossAdjustment.ticker == ticker,
                    StopLossAdjustment.adjustment_type == "trailing",
                    StopLossAdjustment.high_water_mark.isnot(None),
                )
                .order_by(StopLossAdjustment.timestamp.desc())
                .first()
            )
            return float(row.high_water_mark) if row and row.high_water_mark is not None else None
        finally:
            session.close()

    def _record_adjustment(
        self,
        ticker: str,
        adjustment_type: str,
        status: str,
        cycle_id: str | None = None,
        old_stop_price: float | None = None,
        new_stop_price: float | None = None,
        current_price: float | None = None,
        high_water_mark: float | None = None,
        atr_value: float | None = None,
        trigger_reason: str | None = None,
        t212_cancelled_order_id: str | None = None,
        t212_new_order_id: str | None = None,
    ) -> None:
        """Persist a StopLossAdjustment record."""
        session = get_session()
        try:
            session.add(StopLossAdjustment(
                timestamp=datetime.now(timezone.utc),
                cycle_id=cycle_id,
                ticker=ticker,
                adjustment_type=adjustment_type,
                old_stop_price=old_stop_price,
                new_stop_price=new_stop_price,
                current_price=current_price,
                high_water_mark=high_water_mark,
                atr_value=atr_value,
                trigger_reason=trigger_reason,
                t212_cancelled_order_id=t212_cancelled_order_id,
                t212_new_order_id=t212_new_order_id,
                status=status,
            ))
            session.commit()
        except Exception as e:
            logger.error(f"Failed to record stop-loss adjustment: {e}")
            session.rollback()
        finally:
            session.close()

    @staticmethod
    def _extract_atr(stock_data: dict[str, Any]) -> float | None:
        """Extract ATR from stock analysis data."""
        indicators = stock_data.get("indicators", {})
        atr = indicators.get("atr_14") or indicators.get("atr")
        if atr is not None:
            try:
                return float(atr)
            except (TypeError, ValueError):
                return None
        return None
