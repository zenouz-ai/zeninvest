"""Order management with deduplication and execution logic."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

from src.agents.execution.t212_client import T212Client, calculate_quantity
from src.data.database import get_session
from src.data.models import Instrument, Order
from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.scheduling import is_within_regular_market_session

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


def _unwrap_order_http_error(exc: BaseException) -> tuple[BaseException, int | None, str]:
    """Resolve RetryError (tenacity) to inner exception; return status/body snippet if HTTPStatusError."""
    e: BaseException = exc
    inner = getattr(exc, "last_attempt", None)
    if inner is not None and callable(getattr(inner, "exception", None)):
        inner_exc = inner.exception()
        if inner_exc is not None:
            e = inner_exc
    if isinstance(e, httpx.HTTPStatusError):
        text = (e.response.text or "")[:500]
        return e, e.response.status_code, text
    return e, None, str(e)[:500]


def _stop_cancel_is_idempotent_success(status_code: int | None, response_text: str) -> bool:
    """Treat as success when the stop is already gone or not cancelable (idempotent)."""
    if status_code == 404:
        return True
    if status_code in (400, 409):
        low = response_text.lower()
        needles = (
            "not found",
            "no longer",
            "already",
            "cancelled",
            "canceled",
            "not pending",
            "invalid state",
            "does not exist",
            "unknown order",
        )
        return any(n in low for n in needles)
    return False


def _format_http_error_message(exc: BaseException, *, prefix: str) -> str:
    """Return an execution-friendly error message with broker body detail when available."""
    inner_exc, status_code, body_snip = _unwrap_order_http_error(exc)
    if status_code is None:
        return f"{prefix}: {inner_exc}"

    clean_body = " ".join((body_snip or "").split())
    if clean_body:
        return f"{prefix}: HTTP {status_code} {clean_body[:300]}"
    return f"{prefix}: HTTP {status_code}"


def _is_instrument_not_tradable_error(exc: BaseException) -> bool:
    """Detect Trading212 400 payloads indicating the instrument cannot be traded."""
    _, status_code, body_snip = _unwrap_order_http_error(exc)
    if status_code != 400:
        return False
    low = (body_snip or "").lower()
    return "instrument-invisible" in low or "instrument can not be traded" in low


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
        allow_below_min_protective_stop: bool = False,
    ) -> tuple[bool, str | None]:
        """Validate minimum order value policy before executing/logging."""
        if action != "BUY":
            return True, None
        min_order = float(self.settings.min_order_value_gbp)
        if value_gbp >= min_order:
            return True, None
        return False, "below_min_order_value"

    def _make_dedup_key(self, ticker: str, quantity: float) -> str:
        """Create a deduplication key: ticker_direction_absqty."""
        direction = "BUY" if quantity > 0 else "SELL"
        return f"{ticker}_{direction}_{abs(quantity):.2f}"

    def check_off_hours_order_policy(
        self,
        *,
        ticker: str,
        action: str,
        order_type: str,
    ) -> tuple[bool, str | None]:
        """Return whether order placement is allowed and any off-hours warning note."""
        if is_within_regular_market_session(self.settings):
            return True, None

        note = (
            f"Placed {action} {order_type} order for {ticker} outside the regular US market session; "
            "it may remain pending until the market opens."
        )
        logger.warning(note)

        if DASHBOARD_AVAILABLE and log_event is not None:
            try:
                log_event(
                    event_type="order_warning",
                    source="execution",
                    message=note,
                    metadata={
                        "ticker": ticker,
                        "action": action,
                        "order_type": order_type,
                        "warning_note": note,
                    },
                )
            except Exception:
                pass

        if not self.settings.allow_off_hours_orders:
            return False, note
        return True, note

    def _mark_instrument_unavailable(self, ticker: str, reason: str) -> None:
        """Mark instrument as unavailable so future screening/execution can skip it."""
        session = get_session()
        try:
            inst = session.query(Instrument).filter_by(ticker=ticker).first()
            if inst:
                inst.data_available = False
                inst.updated_at = datetime.now(timezone.utc)
                session.commit()
                logger.warning("Marked %s unavailable after execution failure: %s", ticker, reason)
        except Exception as e:
            session.rollback()
            logger.warning("Failed to mark %s unavailable after execution failure: %s", ticker, e)
        finally:
            session.close()

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

    def cancel_conflicting_stops(self, ticker: str) -> dict[str, Any]:
        """Cancel pending stop-loss orders for a ticker before SELL/REDUCE.

        In dry-run mode, queries DB for pending stops and logs what would be
        cancelled. In live mode, fetches pending orders from T212 and cancels
        matching stop orders.

        Returns:
            {"status": "ok", "cancelled": [...]} on success or no stops found.
            {"status": "failed", "error": "..."} on cancellation failure.
        """
        cancelled: list[str] = []

        if self.dry_run:
            # Check local DB for pending stops to log what would happen
            session = get_session()
            try:
                rows = (
                    session.query(Order)
                    .filter(
                        Order.ticker == ticker,
                        Order.order_type == "stop",
                        Order.status.in_(["pending", "dry_run"]),
                    )
                    .all()
                )
                for row in rows:
                    order_id = row.t212_order_id or str(row.id)
                    logger.info(
                        f"[DRY RUN] Would cancel stop-loss for {ticker}: "
                        f"order_id={order_id}, stop_price={row.stop_price}"
                    )
                    row.status = "cancelled"
                    row.error_message = "Cancelled before SELL/REDUCE (dry run)"
                    cancelled.append(order_id)
                if rows:
                    session.commit()
            except Exception:
                session.rollback()
            finally:
                session.close()
            return {"status": "ok", "cancelled": cancelled}

        # Live mode: fetch pending orders from T212
        try:
            pending = self.client.get_pending_orders()
        except Exception as e:
            error_msg = f"Failed to fetch pending orders: {e}"
            logger.error(error_msg)
            return {"status": "failed", "error": error_msg}

        stops_for_ticker = [
            order
            for order in pending
            if order.get("ticker") == ticker
            and (order.get("type") == "STOP" or "stopPrice" in order)
        ]

        if not stops_for_ticker:
            return {"status": "ok", "cancelled": []}

        for stop_order in stops_for_ticker:
            order_id = stop_order.get("id") or stop_order.get("orderId")
            if not order_id:
                continue
            try:
                self.client.cancel_order(str(order_id))
                cancelled.append(str(order_id))
                logger.info(
                    f"Cancelled stop-loss for {ticker} before SELL/REDUCE: "
                    f"order_id={order_id}"
                )
                # Update local DB record
                session = get_session()
                try:
                    row = (
                        session.query(Order)
                        .filter(
                            Order.t212_order_id == str(order_id),
                            Order.status == "pending",
                        )
                        .first()
                    )
                    if row:
                        row.status = "cancelled"
                        row.error_message = "Cancelled before SELL/REDUCE execution"
                        session.commit()
                except Exception:
                    session.rollback()
                finally:
                    session.close()

                # Dashboard event
                if DASHBOARD_AVAILABLE and log_event is not None:
                    try:
                        log_event(
                            event_type="order_adjustment",
                            source="execution",
                            message=f"Cancelled stop-loss for {ticker} before SELL/REDUCE",
                            metadata={
                                "ticker": ticker,
                                "cancelled_order_id": str(order_id),
                                "stop_price": stop_order.get("stopPrice"),
                                "reason": "conflicting_stop_before_sell",
                            },
                        )
                    except Exception:
                        pass  # Fail-open

            except Exception as e:
                inner_exc, status_code, body_snip = _unwrap_order_http_error(e)
                if _stop_cancel_is_idempotent_success(status_code, body_snip):
                    logger.info(
                        f"Stop-loss {order_id} for {ticker} already gone or not cancelable "
                        f"(HTTP {status_code}): {body_snip[:120]!r}"
                    )
                    cancelled.append(str(order_id))
                    continue
                err_flat = f"{inner_exc} {body_snip}".lower()
                if "404" in err_flat or "not found" in err_flat:
                    logger.info(
                        f"Stop-loss {order_id} for {ticker} already gone (triggered or cancelled)"
                    )
                    cancelled.append(str(order_id))
                    continue
                error_msg = f"Failed to cancel stop-loss {order_id} for {ticker}: {e}"
                logger.error(
                    "%s | http_status=%s body_snippet=%r",
                    error_msg,
                    status_code,
                    body_snip[:200],
                )
                return {"status": "failed", "error": error_msg}

        return {"status": "ok", "cancelled": cancelled}

    def cancel_pending_market_sells(self, ticker: str, reason: str) -> dict[str, Any]:
        """Cancel live pending market SELLs for a ticker when a newer cycle says hold off."""
        if self.dry_run:
            return {"status": "ok", "cancelled": [], "local_pending_count": 0, "live_pending_count": 0}

        session = get_session()
        try:
            local_pending = (
                session.query(Order)
                .filter(
                    Order.ticker == ticker,
                    Order.action == "SELL",
                    Order.order_type == "market",
                    Order.status.in_(["pending", "submitting"]),
                    Order.t212_order_id.isnot(None),
                )
                .all()
            )
            if not local_pending:
                return {"status": "ok", "cancelled": [], "local_pending_count": 0, "live_pending_count": 0}

            try:
                live_pending = self.client.get_pending_orders()
            except Exception as e:
                error_msg = f"Failed to fetch pending orders: {e}"
                logger.error(error_msg)
                return {
                    "status": "failed",
                    "error": error_msg,
                    "cancelled": [],
                    "local_pending_count": len(local_pending),
                    "live_pending_count": 0,
                }

            live_pending_ids = {
                str(item.get("id") or item.get("orderId"))
                for item in live_pending
                if (item.get("id") or item.get("orderId")) is not None
            }

            cancelled: list[str] = []
            live_rows = [row for row in local_pending if str(row.t212_order_id) in live_pending_ids]
            for row in live_rows:
                order_id = str(row.t212_order_id)
                try:
                    self.client.cancel_order(order_id)
                    row.status = "cancelled"
                    row.error_message = reason
                    cancelled.append(order_id)
                except Exception as e:
                    inner_exc, status_code, body_snip = _unwrap_order_http_error(e)
                    if _stop_cancel_is_idempotent_success(status_code, body_snip):
                        row.status = "cancelled"
                        row.error_message = reason
                        cancelled.append(order_id)
                        continue
                    error_msg = f"Failed to cancel pending market sell {order_id} for {ticker}: {e}"
                    logger.error(
                        "%s | http_status=%s body_snippet=%r",
                        error_msg,
                        status_code,
                        body_snip[:200],
                    )
                    session.rollback()
                    return {
                        "status": "failed",
                        "error": error_msg,
                        "cancelled": cancelled,
                        "local_pending_count": len(local_pending),
                        "live_pending_count": len(live_rows),
                    }

            if cancelled:
                session.commit()
                logger.info(
                    "Cancelled %d pending market SELL order(s) for %s after newer decision: %s",
                    len(cancelled),
                    ticker,
                    reason,
                )
            return {
                "status": "ok",
                "cancelled": cancelled,
                "local_pending_count": len(local_pending),
                "live_pending_count": len(live_rows),
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _classify_pending_order(
        self,
        live_order: dict[str, Any],
        local_row: Order | None,
    ) -> str | None:
        """Classify a pending broker order as buy, sell, or stop_sell."""
        if local_row is not None:
            if local_row.order_type == "stop":
                return "stop_sell"
            if local_row.action == "BUY":
                return "buy"
            if local_row.action == "SELL":
                return "sell"

        order_type = str(live_order.get("type") or "").upper()
        if order_type == "STOP" or live_order.get("stopPrice") is not None:
            return "stop_sell"

        quantity_raw = live_order.get("quantity")
        try:
            quantity = float(quantity_raw)
        except (TypeError, ValueError):
            quantity = 0.0
        if quantity > 0:
            return "buy"
        if quantity < 0:
            return "sell"

        action = str(live_order.get("action") or live_order.get("side") or "").upper()
        if action == "BUY":
            return "buy"
        if action == "SELL":
            return "sell"
        return None

    def cancel_pending_orders_by_class(
        self,
        *,
        tickers: list[str],
        order_class: str,
        reason: str,
    ) -> dict[str, Any]:
        """Cancel matching pending orders for the given tickers and order class."""
        normalized_tickers = [ticker for ticker in tickers if ticker]
        if not normalized_tickers:
            return {
                "status": "failed",
                "error": "No tickers provided",
                "cancelled": [],
                "matches": [],
                "failures": [],
            }

        session = get_session()
        try:
            local_rows = (
                session.query(Order)
                .filter(
                    Order.ticker.in_(normalized_tickers),
                    Order.status.in_(["pending", "submitting"]),
                    Order.t212_order_id.isnot(None),
                )
                .all()
            )
            local_by_id = {str(row.t212_order_id): row for row in local_rows if row.t212_order_id}

            try:
                live_pending = self.client.get_pending_orders()
            except Exception as e:
                error_msg = f"Failed to fetch pending orders: {e}"
                logger.error(error_msg)
                return {
                    "status": "failed",
                    "error": error_msg,
                    "cancelled": [],
                    "matches": [],
                    "failures": [],
                }

            matches: list[dict[str, Any]] = []
            for live_order in live_pending:
                ticker = str(live_order.get("ticker") or "")
                if ticker not in normalized_tickers:
                    continue
                order_id = live_order.get("id") or live_order.get("orderId")
                if order_id is None:
                    continue
                order_id_str = str(order_id)
                local_row = local_by_id.get(order_id_str)
                classified = self._classify_pending_order(live_order, local_row)
                if classified != order_class:
                    continue
                matches.append(
                    {
                        "order_id": order_id_str,
                        "ticker": ticker,
                        "classified_as": classified,
                        "live_order": live_order,
                    }
                )

            cancelled: list[str] = []
            failures: list[dict[str, str]] = []
            per_ticker: dict[str, dict[str, int]] = {
                ticker: {"matched": 0, "cancelled": 0, "failed": 0}
                for ticker in normalized_tickers
            }
            for match in matches:
                per_ticker[match["ticker"]]["matched"] += 1
                try:
                    self.client.cancel_order(match["order_id"])
                    cancelled.append(match["order_id"])
                    per_ticker[match["ticker"]]["cancelled"] += 1
                    row = local_by_id.get(match["order_id"])
                    if row:
                        row.status = "cancelled"
                        row.error_message = reason
                except Exception as e:
                    inner_exc, status_code, body_snip = _unwrap_order_http_error(e)
                    if _stop_cancel_is_idempotent_success(status_code, body_snip):
                        cancelled.append(match["order_id"])
                        per_ticker[match["ticker"]]["cancelled"] += 1
                        row = local_by_id.get(match["order_id"])
                        if row:
                            row.status = "cancelled"
                            row.error_message = reason
                        continue
                    error_msg = f"{inner_exc}"
                    failures.append(
                        {
                            "order_id": match["order_id"],
                            "ticker": match["ticker"],
                            "error": error_msg,
                        }
                    )
                    per_ticker[match["ticker"]]["failed"] += 1

            if cancelled:
                session.commit()

            if failures and cancelled:
                status = "partial"
            elif failures:
                status = "failed"
            else:
                status = "ok"

            return {
                "status": status,
                "cancelled": cancelled,
                "matches": matches,
                "failures": failures,
                "per_ticker": per_ticker,
                "local_pending_count": len(local_rows),
                "live_pending_count": len(live_pending),
            }
        except Exception:
            session.rollback()
            raise
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
        warning_note: str | None = None,
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
                warning_note=warning_note,
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

    def _update_order_status(
        self,
        order_id: int,
        status: str,
        t212_order_id: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update an existing order record's status (for write-before-execute pattern)."""
        session = get_session()
        try:
            row = session.query(Order).filter(Order.id == order_id).first()
            if row:
                row.status = status
                if t212_order_id:
                    row.t212_order_id = t212_order_id
                if error_message:
                    row.error_message = error_message
                session.commit()
        except Exception:
            session.rollback()
            logger.error(f"Failed to update order {order_id} to status={status}")
        finally:
            session.close()

    def execute_market_order(
        self,
        ticker: str,
        action: str,
        target_amount_gbp: float,
        current_price: float,
        price_gbp: float | None = None,
        strategy: str | None = None,
        conviction: int | None = None,
        moderation_result: str | None = None,
        risk_result: str | None = None,
        quantity_override: float | None = None,
    ) -> dict[str, Any]:
        """Execute a market order with deduplication.

        Args:
            ticker: Instrument ticker (e.g., "AAPL_US_EQ")
            action: BUY, SELL, or REDUCE
            target_amount_gbp: Target trade value in GBP
            current_price: Current market price in the instrument's native currency (USD for US stocks)
            price_gbp: current_price converted to GBP. When provided, used for quantity
                calculation and value_gbp logging (SELL/REDUCE). Falls back to current_price
                when None (backward-compatible).
            strategy: Which strategy triggered this
            conviction: Conviction score
            moderation_result: Moderation panel result
            risk_result: Risk agent result
            quantity_override: When set, use this quantity directly instead of calculating
                from target_amount_gbp. Used by Slack trade commands with explicit share count.
        """
        if action == "BUY" and quantity_override is None:
            min_order = float(self.settings.min_order_value_gbp)
            if 0 < target_amount_gbp < min_order:
                logger.info(
                    f"Upgrading BUY {ticker} target from £{target_amount_gbp:.2f} "
                    f"to minimum order £{min_order:.2f}"
                )
                target_amount_gbp = min_order

        if quantity_override is not None and quantity_override > 0:
            quantity = quantity_override
        else:
            quantity = calculate_quantity(
                target_amount_gbp,
                price_gbp or current_price,
                prefer_whole_shares=(
                    action == "BUY"
                    and self.settings.buy_whole_shares_preferred
                ),
                max_overspend_pct=self.settings.buy_whole_share_max_overspend_pct,
                allow_fractional_fallback=self.settings.buy_fractional_fallback_enabled,
            )
        if quantity <= 0:
            logger.warning(f"Calculated quantity is 0 for {ticker} @ {current_price}")
            return {
                "status": "skipped",
                "reason": "zero_quantity",
                "ticker": ticker,
                "action": action,
                "quantity": 0.0,
                "price": current_price,
                "value_gbp": 0.0,
            }

        if action in ("SELL", "REDUCE"):
            quantity = -quantity

        # SELL/REDUCE: cancel stops first, then clamp to broker position (reduces T212 400 oversell).
        if action in ("SELL", "REDUCE"):
            cancel_result = self.cancel_conflicting_stops(ticker)
            if cancel_result.get("status") == "failed":
                error_msg = (
                    f"Cannot {action} {ticker}: failed to cancel conflicting "
                    f"stop-loss: {cancel_result.get('error', 'unknown')}"
                )
                logger.error(error_msg)
                pre_dedup = self._make_dedup_key(ticker, quantity)
                fail_row = self._log_order(
                    ticker=ticker,
                    action=action,
                    order_type="market",
                    quantity=quantity,
                    price=current_price,
                    value_gbp=abs(quantity) * current_price,
                    status="failed",
                    strategy=strategy,
                    conviction=conviction,
                    moderation_result=moderation_result,
                    risk_result=risk_result,
                    error_message=error_msg,
                    dedup_key=pre_dedup,
                )
                return {
                    "status": "failed",
                    "error": error_msg,
                    "order_id": fail_row.id,
                    "ticker": ticker,
                    "action": action,
                    "quantity": abs(quantity),
                    "price": current_price,
                    "value_gbp": abs(quantity) * current_price,
                }
            if cancel_result.get("cancelled"):
                logger.info(
                    f"Cancelled {len(cancel_result['cancelled'])} stop-loss order(s) "
                    f"for {ticker} before {action}"
                )

            try:
                pos = self.client.get_position(ticker)
            except Exception as e:
                error_msg = f"Cannot {action} {ticker}: failed to fetch position for quantity clamp: {e}"
                logger.error(error_msg)
                pre_dedup = self._make_dedup_key(ticker, quantity)
                fail_row = self._log_order(
                    ticker=ticker,
                    action=action,
                    order_type="market",
                    quantity=quantity,
                    price=current_price,
                    value_gbp=abs(quantity) * current_price,
                    status="failed",
                    strategy=strategy,
                    conviction=conviction,
                    moderation_result=moderation_result,
                    risk_result=risk_result,
                    error_message=error_msg,
                    dedup_key=pre_dedup,
                )
                return {
                    "status": "failed",
                    "error": error_msg,
                    "order_id": fail_row.id,
                    "ticker": ticker,
                    "action": action,
                    "quantity": abs(quantity),
                    "price": current_price,
                    "value_gbp": abs(quantity) * current_price,
                }

            available = float(pos.get("quantity", 0) or 0)
            if available <= 0:
                error_msg = (
                    f"No shares available to {action} {ticker} "
                    "(broker position quantity is 0 or instrument not held)"
                )
                logger.error(error_msg)
                pre_dedup = self._make_dedup_key(ticker, quantity)
                fail_row = self._log_order(
                    ticker=ticker,
                    action=action,
                    order_type="market",
                    quantity=quantity,
                    price=current_price,
                    value_gbp=abs(quantity) * current_price,
                    status="failed",
                    strategy=strategy,
                    conviction=conviction,
                    moderation_result=moderation_result,
                    risk_result=risk_result,
                    error_message=error_msg,
                    dedup_key=pre_dedup,
                )
                return {
                    "status": "failed",
                    "error": error_msg,
                    "order_id": fail_row.id,
                    "ticker": ticker,
                    "action": action,
                    "quantity": abs(quantity),
                    "price": current_price,
                    "value_gbp": abs(quantity) * current_price,
                }

            if action == "SELL" and (quantity_override is None or quantity_override <= 0):
                quantity = -available
            abs_req = abs(quantity)
            if abs_req > available:
                logger.warning(
                    f"Clamping {action} quantity for {ticker} from {abs_req} to {available} "
                    "(broker-reported position)"
                )
                quantity = -available

            if abs(quantity) <= 0:
                return {
                    "status": "skipped",
                    "reason": "zero_quantity",
                    "ticker": ticker,
                    "action": action,
                    "quantity": 0.0,
                    "price": current_price,
                    "value_gbp": 0.0,
                }

        dedup_key = self._make_dedup_key(ticker, quantity)

        if self._is_duplicate(dedup_key):
            logger.warning(f"Duplicate order detected: {dedup_key}")
            computed_dup = abs(quantity) * current_price
            return {
                "status": "skipped",
                "reason": "duplicate",
                "ticker": ticker,
                "action": action,
                "quantity": abs(quantity),
                "price": current_price,
                "value_gbp": float(abs(target_amount_gbp)) if action == "BUY" else computed_dup,
            }

        computed_value_gbp = abs(quantity) * (price_gbp or current_price)
        # Min-order policy is based on the *target* trade value (pre quantity flooring)
        # for BUY orders. This avoids off-by-a-few-pence skips when the share quantity
        # is rounded down to 2 decimals.
        if action == "BUY":
            value_gbp = float(abs(target_amount_gbp))
        else:
            value_gbp = computed_value_gbp
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
            return {
                "status": "skipped",
                "reason": reject_reason,
                "ticker": ticker,
                "action": action,
                "quantity": abs(quantity),
                "price": current_price,
                "value_gbp": value_gbp,
            }

        can_place_off_hours, warning_note = self.check_off_hours_order_policy(
            ticker=ticker,
            action=action,
            order_type="market",
        )
        if not can_place_off_hours:
            return {
                "status": "skipped",
                "reason": "outside_regular_market_session",
                "ticker": ticker,
                "action": action,
                "quantity": abs(quantity),
                "price": current_price,
                "value_gbp": value_gbp,
                "warning_note": warning_note,
            }

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
                warning_note=warning_note,
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
                            "warning_note": warning_note,
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
                "warning_note": warning_note,
            }

        # Write-before-execute: create a "submitting" DB record BEFORE the T212
        # API call. If the process crashes after T212 accepts but before we update,
        # the orphaned "submitting" record enables crash recovery. (Audit fix C-2.)
        order = self._log_order(
            ticker=ticker,
            action=action,
            order_type="market",
            quantity=quantity,
            price=current_price,
            value_gbp=value_gbp,
            status="submitting",
            strategy=strategy,
            conviction=conviction,
            moderation_result=moderation_result,
            risk_result=risk_result,
            dedup_key=dedup_key,
            warning_note=warning_note,
        )

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
                            "warning_note": warning_note,
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

            # Update the pre-written record with T212 response
            self._update_order_status(order.id, db_status, t212_order_id=str(t212_order_id) if t212_order_id else None)

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
                            "warning_note": warning_note,
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
                "warning_note": warning_note,
            }

        except Exception as e:
            error_msg = _format_http_error_message(e, prefix=f"Order failed for {ticker}")
            if action == "BUY" and _is_instrument_not_tradable_error(e):
                self._mark_instrument_unavailable(
                    ticker,
                    "t212_instrument_not_tradable",
                )
            logger.error("%s", error_msg)
            # Update the pre-written record to failed
            self._update_order_status(order.id, "failed", error_message=error_msg)
            return {
                "status": "failed",
                "error": error_msg,
                "order_id": order.id,
                "ticker": ticker,
                "action": action,
                "quantity": abs(quantity),
                "price": current_price,
                "value_gbp": value_gbp,
                "warning_note": warning_note,
            }

    def sync_order_status_from_t212(self) -> int:
        """Sync pending orders with T212 order history. Updates local Order.status to filled when T212 reports FILLED.

        Returns:
            Number of orders updated.
        """
        summary = self.sync_orders_with_t212()
        return int(summary.get("filled_count", 0))

    @staticmethod
    def _map_t212_status_to_order_status(t212_status: str) -> str:
        """Map T212 order status values to local DB status values."""
        upper = (t212_status or "").upper()
        if upper in ("FILLED", "PARTIALLY_FILLED"):
            return "filled"
        if upper in ("REJECTED",):
            return "failed"
        if upper in ("CANCELLED", "CANCELLING"):
            return "cancelled"
        return "pending"

    def sync_orders_with_t212(
        self,
        *,
        order_type_filter: set[str] | None = None,
    ) -> dict[str, Any]:
        """Sync local pending orders against T212 history and live pending orders."""
        if self.dry_run:
            return {
                "pending_local_count": 0,
                "pending_live_count": 0,
                "stale_pending_count": 0,
                "reconciled_pending_count": 0,
                "filled_count": 0,
                "cancelled_count": 0,
                "failed_count": 0,
                "updated_total": 0,
                "history_fetch_error": None,
                "live_fetch_error": None,
                "last_broker_sync_at": None,
                "last_history_sync_at": None,
                "last_live_pending_sync_at": None,
                "history_fetch_error_at": None,
                "live_fetch_error_at": None,
            }

        session = get_session()
        try:
            query = (
                session.query(Order)
                .filter(
                    Order.status.in_(["pending", "submitting"]),
                    Order.t212_order_id.isnot(None),
                )
            )
            if order_type_filter:
                query = query.filter(Order.order_type.in_(sorted(order_type_filter)))
            local_pending = query.all()
            pending_local_count = len(local_pending)
            if pending_local_count == 0:
                return {
                    "pending_local_count": 0,
                    "pending_live_count": 0,
                    "stale_pending_count": 0,
                    "reconciled_pending_count": 0,
                    "filled_count": 0,
                    "cancelled_count": 0,
                    "failed_count": 0,
                    "updated_total": 0,
                    "history_fetch_error": None,
                    "live_fetch_error": None,
                    "last_broker_sync_at": None,
                    "last_history_sync_at": None,
                    "last_live_pending_sync_at": None,
                    "history_fetch_error_at": None,
                    "live_fetch_error_at": None,
                }

            local_by_id = {
                str(row.t212_order_id): row for row in local_pending if row.t212_order_id is not None
            }
            filled_count = 0
            cancelled_count = 0
            failed_count = 0
            history_fetch_error = None
            history_fetch_error_at = None
            cursor: str | None = None
            t212_ids_seen: set[str] = set()
            terminal_ids_seen: set[str] = set()
            last_history_sync_at = None

            try:
                while True:
                    resp = self.client.get_order_history(cursor=cursor, limit=50)
                    last_history_sync_at = datetime.now(timezone.utc)
                    items = resp.get("items") or []
                    next_page = resp.get("nextPagePath")

                    for item in items:
                        order_obj = item.get("order") if isinstance(item, dict) else None
                        if not order_obj:
                            continue
                        t212_id = str(order_obj.get("id") or order_obj.get("orderId") or "")
                        if not t212_id or t212_id in t212_ids_seen or t212_id not in local_by_id:
                            continue
                        t212_ids_seen.add(t212_id)
                        row = local_by_id[t212_id]
                        db_status = self._map_t212_status_to_order_status(str(order_obj.get("status") or ""))
                        if db_status == "pending":
                            continue

                        row.status = db_status
                        if db_status == "cancelled":
                            row.error_message = "Synced from T212 order history"
                        elif db_status == "failed":
                            row.error_message = "Rejected by T212"
                        filled_qty = order_obj.get("filledQuantity")
                        filled_val = order_obj.get("filledValue")
                        if db_status == "filled" and filled_qty is not None and filled_qty > 0 and row.price is None:
                            row.price = (filled_val or 0) / filled_qty if filled_val else None

                        terminal_ids_seen.add(t212_id)
                        if db_status == "filled":
                            filled_count += 1
                        elif db_status == "cancelled":
                            cancelled_count += 1
                        elif db_status == "failed":
                            failed_count += 1

                    if not next_page or len(items) < 50 or terminal_ids_seen == set(local_by_id):
                        break
                    cursor = next_page
            except Exception as e:
                history_fetch_error = str(e)
                history_fetch_error_at = datetime.now(timezone.utc)
                logger.warning(f"Order status sync failed: {e}")

            live_fetch_error = None
            live_fetch_error_at = None
            pending_live_count = 0
            reconciled_pending_count = 0
            stale_pending_count = 0
            last_live_pending_sync_at = None
            try:
                live_pending = self.client.get_pending_orders()
                last_live_pending_sync_at = datetime.now(timezone.utc)
                live_pending_ids = {
                    str(item.get("id") or item.get("orderId"))
                    for item in live_pending
                    if (item.get("id") or item.get("orderId")) is not None
                }
                pending_live_count = len(live_pending_ids)

                stale_rows = [
                    row
                    for order_id, row in local_by_id.items()
                    if row.status in ("pending", "submitting") and order_id not in live_pending_ids
                ]
                stale_pending_count = len(stale_rows)
                for row in stale_rows:
                    row.status = "cancelled"
                    row.error_message = "Reconciled: missing from live T212 pending orders"
                reconciled_pending_count = len(stale_rows)
                cancelled_count += reconciled_pending_count
            except Exception as e:
                live_fetch_error = str(e)
                live_fetch_error_at = datetime.now(timezone.utc)
                logger.warning(f"Pending order reconciliation skipped: failed to fetch live pending orders: {e}")

            session.commit()
            updated_total = filled_count + cancelled_count + failed_count
            last_broker_sync_at = max(
                [ts for ts in (last_history_sync_at, last_live_pending_sync_at) if ts is not None],
                default=None,
            )
            if updated_total:
                logger.info(
                    "Order sync updated %s orders (filled=%s cancelled=%s failed=%s)",
                    updated_total,
                    filled_count,
                    cancelled_count,
                    failed_count,
                )
            return {
                "pending_local_count": pending_local_count,
                "pending_live_count": pending_live_count,
                "stale_pending_count": stale_pending_count,
                "reconciled_pending_count": reconciled_pending_count,
                "filled_count": filled_count,
                "cancelled_count": cancelled_count,
                "failed_count": failed_count,
                "updated_total": updated_total,
                "history_fetch_error": history_fetch_error,
                "live_fetch_error": live_fetch_error,
                "last_broker_sync_at": last_broker_sync_at,
                "last_history_sync_at": last_history_sync_at,
                "last_live_pending_sync_at": last_live_pending_sync_at,
                "history_fetch_error_at": history_fetch_error_at,
                "live_fetch_error_at": live_fetch_error_at,
            }
        except Exception as e:
            session.rollback()
            err = str(e)
            logger.warning(f"Order sync failed: {err}")
            return {
                "pending_local_count": 0,
                "pending_live_count": 0,
                "stale_pending_count": 0,
                "reconciled_pending_count": 0,
                "filled_count": 0,
                "cancelled_count": 0,
                "failed_count": 0,
                "updated_total": 0,
                "history_fetch_error": err,
                "live_fetch_error": None,
                "last_broker_sync_at": None,
                "last_history_sync_at": None,
                "last_live_pending_sync_at": None,
                "history_fetch_error_at": datetime.now(timezone.utc),
                "live_fetch_error_at": None,
            }
        finally:
            session.close()

    def reconcile_pending_stop_orders_with_t212(self) -> dict[str, Any]:
        """Reconcile local pending stop orders against live T212 pending orders.

        Local rows that are pending in DB but missing from live T212 pending orders
        are stale and are updated to cancelled.
        """
        return self.sync_orders_with_t212(order_type_filter={"stop"})

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
        current_price_gbp: float | None = None,
    ) -> dict[str, Any]:
        """Place a stop-loss order for a position.

        Args:
            ticker: Instrument ticker (e.g., "AAPL_US_EQ")
            quantity: Number of shares to protect (positive).
            current_price: Current market price in native currency (USD for US stocks).
                Used for the stop trigger price sent to T212 (must be in native currency).
            stop_loss_pct: Negative percentage (e.g., -8.0 for 8% below).
            strategy: Which strategy triggered this.
            current_price_gbp: current_price converted to GBP. When provided, used for
                value_gbp logging only. Falls back to current_price when None.

        Returns:
            Result dict with order status.
        """
        if stop_loss_pct >= 0 or quantity <= 0:
            return {"status": "skipped", "reason": "invalid_stop_loss_params"}

        stop_price = round(current_price * (1 + stop_loss_pct / 100), 2)
        sell_quantity = -quantity  # Negative for sell
        stop_order_value = abs(sell_quantity) * (current_price_gbp or current_price)
        can_place, reject_reason = self._passes_min_order_value(
            action="SELL",
            order_type="stop",
            value_gbp=stop_order_value,
            allow_below_min_full_sell=False,
            allow_below_min_protective_stop=True,
        )
        if not can_place:
            logger.info(
                f"Stop-loss skipped: {ticker} value £{stop_order_value:.2f} below minimum "
                f"£{self.settings.min_order_value_gbp:.2f}"
            )
            return {"status": "skipped", "order_type": "stop", "reason": reject_reason}

        can_place_off_hours, warning_note = self.check_off_hours_order_policy(
            ticker=ticker,
            action="SELL",
            order_type="stop",
        )
        if not can_place_off_hours:
            return {
                "status": "skipped",
                "order_type": "stop",
                "reason": "outside_regular_market_session",
                "warning_note": warning_note,
            }

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
                warning_note=warning_note,
            )
            return {
                "status": "dry_run",
                "order_type": "stop",
                "order_id": order.id,
                "ticker": ticker,
                "stop_price": stop_price,
                "quantity": quantity,
                "warning_note": warning_note,
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
                warning_note=warning_note,
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
                "warning_note": warning_note,
            }
        except Exception as e:
            error_msg = _format_http_error_message(e, prefix=f"Stop-loss order failed for {ticker}")
            logger.error("%s", error_msg)
            self._log_order(
                ticker=ticker,
                action="SELL",
                order_type="stop",
                quantity=sell_quantity,
                stop_price=stop_price,
                value_gbp=stop_order_value,
                status="failed",
                strategy=strategy,
                warning_note=warning_note,
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
                        _, warning_note = self.check_off_hours_order_policy(
                            ticker=ticker,
                            action="SELL",
                            order_type="market",
                        )
                        # Cancel conflicting stops (fail-open for liquidation)
                        try:
                            self.cancel_conflicting_stops(ticker)
                        except Exception as e:
                            logger.warning(f"Stop cancel failed during liquidation of {ticker}: {e}")
                        result = self.client.place_market_order(ticker, -quantity)
                        # Map T212 status properly — do not assume filled (audit fix C-3)
                        t212_order_id = result.get("id") or result.get("orderId")
                        t212_status = (result.get("status") or "").upper()
                        if t212_status in ("FILLED", "PARTIALLY_FILLED"):
                            db_status = "filled"
                        elif t212_status in ("REJECTED", "CANCELLED", "CANCELLING"):
                            db_status = "failed"
                            logger.warning(f"Liquidation order for {ticker} was {t212_status}")
                        else:
                            db_status = "pending"
                        self._log_order(
                            ticker=ticker,
                            action="SELL",
                            order_type="market",
                            quantity=-quantity,
                            t212_order_id=str(t212_order_id) if t212_order_id else None,
                            status=db_status,
                            strategy="liquidation",
                            warning_note=warning_note,
                        )
                        results.append({"ticker": ticker, "status": db_status, "result": result})
                        logger.info(f"Liquidated {quantity} x {ticker} (status={db_status})")
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
