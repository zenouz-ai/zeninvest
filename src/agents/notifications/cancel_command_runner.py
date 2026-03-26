"""Cancel runner for Slack cancel commands."""

from typing import Any

from src.agents.execution.order_manager import OrderManager
from src.agents.notifications.trade_command_parser import TradeCommandIntent
from src.orchestrator.single_ticker_run import (
    SingleTickerResult,
    build_slack_cycle_id,
    log_slack_command,
    update_slack_command_log,
)
from src.utils.logger import get_logger
from src.utils.ticker_utils import t212_to_yf

logger = get_logger("cancel_command_runner")


class CancelCommandRunner:
    """Cancel pending Trading 212 orders for Slack cancel commands."""

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self._order_manager: OrderManager | None = None

    @property
    def order_manager(self) -> OrderManager:
        if self._order_manager is None:
            self._order_manager = OrderManager(dry_run=self.dry_run)
        return self._order_manager

    def run(
        self,
        *,
        ticker_t212s: list[str],
        intent: TradeCommandIntent,
        user_id: str | None = None,
        channel_id: str | None = None,
        thread_ts: str | None = None,
    ) -> SingleTickerResult:
        cycle_id = build_slack_cycle_id()
        primary_ticker = ticker_t212s[0] if ticker_t212s else ""
        result = SingleTickerResult(
            ticker_t212=primary_ticker,
            ticker_yf=(t212_to_yf(primary_ticker) if primary_ticker else ""),
            cycle_id=cycle_id,
            user_action="CANCEL",
            command_kind=intent.command_kind,
            execution_mode=intent.execution_mode,
            trigger_strategy=False,
            cancel_order_class=intent.cancel_order_class,
            target_tickers=ticker_t212s,
        )

        cmd_log = log_slack_command(
            intent=intent,
            ticker=primary_ticker,
            cycle_id=cycle_id,
            target_tickers=ticker_t212s,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
        )
        result.command_log_id = cmd_log

        if not ticker_t212s:
            result.status = "rejected"
            result.rejection_reason = "Cancel commands require at least one ticker."
            update_slack_command_log(cmd_log, status="rejected", rejection_reason=result.rejection_reason)
            return result
        if intent.cancel_order_class not in {"buy", "sell", "stop_sell"}:
            result.status = "rejected"
            result.rejection_reason = "Cancel commands must specify buy, sell, or stop sell."
            update_slack_command_log(cmd_log, status="rejected", rejection_reason=result.rejection_reason)
            return result

        try:
            cancel_result = self.order_manager.cancel_pending_orders_by_class(
                tickers=ticker_t212s,
                order_class=intent.cancel_order_class,
                reason=f"Cancelled by Slack command: {intent.raw_message}",
            )
            result.result_details = cancel_result
            cancelled_count = len(cancel_result.get("cancelled", []))
            matched_count = len(cancel_result.get("matches", []))
            failure_count = len(cancel_result.get("failures", []))
            result.quantity = float(cancelled_count)
            result.value_gbp = 0.0
            result.execution_result = {
                "order_class": intent.cancel_order_class,
                "cancelled_count": cancelled_count,
                "matched_count": matched_count,
                "failure_count": failure_count,
            }

            if cancel_result.get("status") == "failed":
                result.status = "error"
                result.error_message = cancel_result.get("error") or "Cancel request failed"
                update_slack_command_log(
                    cmd_log,
                    status="error",
                    rejection_reason=result.error_message,
                    result_json=cancel_result,
                )
            elif cancel_result.get("status") == "partial":
                result.status = "partial"
                result.rejection_reason = "Some matching orders were cancelled, but some cancellations failed."
                update_slack_command_log(
                    cmd_log,
                    status="partial",
                    rejection_reason=result.rejection_reason,
                    result_json=cancel_result,
                )
            else:
                result.status = "executed"
                update_slack_command_log(
                    cmd_log,
                    status="executed",
                    result_json=cancel_result,
                )
            return result
        except Exception as e:
            logger.error("[%s] Cancel command error: %s", cycle_id, e, exc_info=True)
            result.status = "error"
            result.error_message = str(e)
            update_slack_command_log(cmd_log, status="error", rejection_reason=str(e))
            return result

    def close(self) -> None:
        if self._order_manager is not None:
            try:
                self._order_manager.close()
            except Exception:
                pass
