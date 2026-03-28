"""Direct trade runner for Slack BUY/SELL commands.

Executes manual trades without strategy, moderation, or risk review while still
preserving pricing, preflight validation, confirmation, execution, and audit.
"""

from typing import Any

from src.agents.conversation.trade_execution_service import PortfolioService
from src.agents.execution.order_manager import OrderManager
from src.agents.execution.t212_client import T212Client
from src.agents.market_data.data_fetcher import DataFetcher
from src.agents.notifications.trade_command_parser import TradeCommandIntent
from src.orchestrator.single_ticker_run import (
    PreparedTradeExecution,
    SingleTickerResult,
    build_slack_cycle_id,
    log_slack_command,
    update_slack_command_log,
)
from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.ticker_utils import t212_to_yf

logger = get_logger("direct_trade_run")


class DirectTradeRunner:
    """Run a direct BUY/SELL Slack trade without strategy, moderation, or risk."""

    def __init__(self, dry_run: bool = False) -> None:
        self.settings = get_settings()
        self.dry_run = dry_run
        self.data_fetcher = DataFetcher()
        self._t212_client: T212Client | None = None
        self._order_manager: OrderManager | None = None
        self._portfolio_service: PortfolioService | None = None

    @property
    def t212_client(self) -> T212Client:
        if self._t212_client is None:
            self._t212_client = T212Client()
        return self._t212_client

    @property
    def order_manager(self) -> OrderManager:
        if self._order_manager is None:
            self._order_manager = OrderManager(dry_run=self.dry_run)
        return self._order_manager

    @property
    def portfolio_service(self) -> PortfolioService:
        if self._portfolio_service is None:
            self._portfolio_service = PortfolioService(
                t212_client=self._t212_client,
                data_fetcher=self.data_fetcher,
            )
        return self._portfolio_service

    def run(
        self,
        ticker_t212: str,
        intent: TradeCommandIntent,
        user_id: str | None = None,
        channel_id: str | None = None,
        thread_ts: str | None = None,
        *,
        log_command: bool = True,
    ) -> SingleTickerResult:
        result = self.prepare(
            ticker_t212=ticker_t212,
            intent=intent,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            log_command=log_command,
        )
        if result.status != "ready":
            return result
        return self.execute_prepared(result)

    def prepare(
        self,
        ticker_t212: str,
        intent: TradeCommandIntent,
        user_id: str | None = None,
        channel_id: str | None = None,
        thread_ts: str | None = None,
        *,
        log_command: bool = True,
    ) -> SingleTickerResult:
        ticker_yf = t212_to_yf(ticker_t212)
        cycle_id = build_slack_cycle_id()
        result = SingleTickerResult(
            ticker_t212=ticker_t212,
            ticker_yf=ticker_yf,
            cycle_id=cycle_id,
            user_action=intent.action,
            command_kind=intent.command_kind,
            execution_mode=intent.execution_mode,
            trigger_strategy=intent.trigger_strategy,
            cancel_order_class=intent.cancel_order_class,
            target_tickers=[ticker_t212],
        )
        if intent.force:
            result.result_details = {"force_ignored": True}

        cmd_log = None
        if log_command:
            cmd_log = log_slack_command(
                intent=intent,
                ticker=ticker_t212,
                cycle_id=cycle_id,
                target_tickers=[ticker_t212],
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
            )
        result.command_log_id = cmd_log

        try:
            validation_error = self._validate_action(intent)
            if validation_error:
                result.status = "rejected"
                result.rejection_reason = validation_error
                update_slack_command_log(cmd_log, status="rejected", rejection_reason=validation_error)
                return result

            stock_data = self.data_fetcher.get_stock_analysis_lite(ticker_yf)
            if not stock_data or stock_data.get("error"):
                result.status = "error"
                result.error_message = f"Data fetch failed for {ticker_yf}"
                update_slack_command_log(cmd_log, status="error", rejection_reason=result.error_message)
                return result

            current_price = self._extract_price(stock_data)
            if not current_price or current_price <= 0:
                result.status = "error"
                result.error_message = f"Could not determine price for {ticker_yf}"
                update_slack_command_log(cmd_log, status="error", rejection_reason=result.error_message)
                return result
            result.price = current_price

            portfolio_data = self._get_portfolio_data()
            price_gbp = self._compute_fx_price_gbp(current_price, ticker_t212, portfolio_data)
            result.price_gbp = price_gbp

            target_amount_gbp, quantity_override = self._resolve_trade_sizing(
                ticker_t212=ticker_t212,
                intent=intent,
                current_price_gbp=price_gbp,
            )
            preflight_error = self._validate_preflight(
                ticker_t212=ticker_t212,
                intent=intent,
                target_amount_gbp=target_amount_gbp,
                quantity_override=quantity_override,
            )
            if preflight_error:
                result.status = "rejected"
                result.rejection_reason = preflight_error
                update_slack_command_log(cmd_log, status="rejected", rejection_reason=preflight_error)
                return result

            result.quantity = abs(quantity_override) if quantity_override is not None else (
                abs(target_amount_gbp / price_gbp) if price_gbp > 0 else 0.0
            )
            result.value_gbp = max(target_amount_gbp, 0.0)

            result.prepared_execution = PreparedTradeExecution(
                action=intent.action,
                target_amount_gbp=target_amount_gbp,
                current_price=current_price,
                price_gbp=price_gbp,
                quantity_override=quantity_override,
                strategy="slack_direct",
                conviction=0,
                moderation_result="NOT_RUN",
                risk_result="NOT_RUN",
                moderation_overridden=False,
                execution_mode="direct",
            )
            result.status = "ready"
            return result

        except Exception as e:
            logger.error("[%s] Direct trade preparation error: %s", cycle_id, e, exc_info=True)
            result.status = "error"
            result.error_message = str(e)
            update_slack_command_log(cmd_log, status="error", rejection_reason=str(e))
            return result

    def execute_prepared(self, result: SingleTickerResult) -> SingleTickerResult:
        if result.prepared_execution is None:
            raise ValueError("SingleTickerResult has no prepared execution payload")

        execution = result.prepared_execution
        exec_result = self.order_manager.execute_market_order(
            ticker=result.ticker_t212,
            action=execution.action,
            target_amount_gbp=execution.target_amount_gbp,
            current_price=execution.current_price,
            price_gbp=execution.price_gbp,
            strategy=execution.strategy,
            conviction=execution.conviction,
            moderation_result=execution.moderation_result,
            risk_result=execution.risk_result,
            quantity_override=execution.quantity_override,
        )

        result.execution_result = exec_result
        result.quantity = abs(exec_result.get("quantity", result.quantity))
        result.value_gbp = exec_result.get("value_gbp", result.value_gbp)

        if exec_result.get("status") in ("filled", "dry_run", "pending"):
            result.status = "executed"
            update_slack_command_log(
                result.command_log_id,
                status="executed",
                order_id=exec_result.get("order_id"),
                result_json=exec_result,
            )
        elif exec_result.get("status") == "skipped":
            result.status = "rejected"
            result.rejection_reason = self._format_execution_rejection(exec_result)
            update_slack_command_log(
                result.command_log_id,
                status="rejected",
                rejection_reason=result.rejection_reason,
                result_json=exec_result,
            )
        else:
            result.status = "error"
            result.error_message = exec_result.get("error") or exec_result.get("reason", "Execution failed")
            update_slack_command_log(
                result.command_log_id,
                status="error",
                rejection_reason=result.error_message,
                result_json=exec_result,
            )

        return result

    def _validate_action(self, intent: TradeCommandIntent) -> str | None:
        if intent.action not in {"BUY", "SELL"}:
            return f"Direct trade mode does not support {intent.action}"
        return None

    def _validate_preflight(
        self,
        *,
        ticker_t212: str,
        intent: TradeCommandIntent,
        target_amount_gbp: float,
        quantity_override: float | None,
    ) -> str | None:
        if intent.action == "BUY":
            cash = self._get_available_cash_gbp()
            required_cash = target_amount_gbp
            if quantity_override is None and self.settings.buy_whole_shares_preferred:
                required_cash *= 1 + (self.settings.buy_whole_share_max_overspend_pct / 100)
            if cash < required_cash:
                return f"Insufficient cash. Available: £{cash:.2f}, required: £{required_cash:.2f}"
            return None

        position = self.t212_client.get_position(ticker_t212)
        qty = float(position.get("quantity", 0) or 0)
        if qty <= 0:
            return f"No open position in {ticker_t212}"
        if quantity_override is not None and quantity_override > qty:
            return f"Requested {quantity_override} shares but only hold {qty}"
        return None

    def _resolve_trade_sizing(
        self,
        *,
        ticker_t212: str,
        intent: TradeCommandIntent,
        current_price_gbp: float,
    ) -> tuple[float, float | None]:
        if intent.action == "SELL":
            position = self.t212_client.get_position(ticker_t212)
            held_qty = float(position.get("quantity", 0) or 0)
            quantity_override = intent.quantity_shares or held_qty
            return quantity_override * current_price_gbp, quantity_override

        quantity_override = intent.quantity_shares
        if intent.amount_gbp is not None:
            amount = float(intent.amount_gbp)
            if quantity_override is None:
                amount = max(amount, float(self.settings.min_order_value_gbp))
            return amount, quantity_override
        if quantity_override is not None:
            return float(quantity_override) * current_price_gbp, quantity_override
        return float(self.settings.min_order_value_gbp), None

    def _format_execution_rejection(self, exec_result: dict[str, Any]) -> str:
        reason = str(exec_result.get("reason", "")).strip()
        if reason == "below_min_order_value":
            value = float(exec_result.get("value_gbp", 0) or 0)
            min_order = float(self.settings.min_order_value_gbp)
            return (
                f"Order value £{value:.2f} is below the minimum order size "
                f"of £{min_order:.2f}"
            )
        if reason == "duplicate":
            return "A matching order was already placed recently."
        if reason == "zero_quantity":
            return "Calculated order quantity is zero."
        return reason or "Execution failed"

    def _get_portfolio_data(self) -> dict[str, Any]:
        """Delegates to PortfolioService."""
        return self.portfolio_service.get_portfolio_data(caller="direct_trade_run")

    def _extract_price(self, stock_data: dict[str, Any]) -> float | None:
        """Delegates to PortfolioService."""
        return self.portfolio_service.extract_price(stock_data)

    def _compute_fx_price_gbp(
        self, current_price: float, ticker: str, portfolio_data: dict[str, Any] | None
    ) -> float:
        """Delegates to PortfolioService."""
        return self.portfolio_service.compute_fx_price_gbp(current_price, ticker, portfolio_data)

    @staticmethod
    def _compute_position_value_scale(positions: list[dict[str, Any]], invested_gbp: float) -> float:
        return PortfolioService.compute_position_value_scale(positions, invested_gbp)

    def _extract_available_cash(self, cash_data: Any) -> float:
        return PortfolioService.extract_available_cash(cash_data)

    def _extract_reserved_cash(self, cash_data: Any) -> float:
        return PortfolioService.extract_reserved_cash(cash_data)

    def _get_total_value_gbp(
        self,
        account_summary: dict[str, Any],
        cash_data: Any,
        positions: list[dict[str, Any]],
    ) -> float:
        return self.portfolio_service.get_total_value_gbp(account_summary, cash_data, positions)

    def _get_available_cash_gbp(self) -> float:
        return self.portfolio_service.get_available_cash_gbp()

    def close(self) -> None:
        self.data_fetcher.close()
        if self._t212_client:
            self._t212_client.close()

    def update_command_log_entry(
        self,
        log_id: int | None,
        status: str | None = None,
        order_id: int | None = None,
        rejection_reason: str | None = None,
        response_message: str | None = None,
        result_json: dict[str, Any] | None = None,
    ) -> None:
        update_slack_command_log(
            log_id,
            status=status,
            order_id=order_id,
            rejection_reason=rejection_reason,
            response_message=response_message,
            result_json=result_json,
        )
