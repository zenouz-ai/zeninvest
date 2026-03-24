"""Inbound command gateway for ChatOps trade controls (US-1.6).

Routes parsed commands to the single-ticker pipeline. Handles ticker resolution,
command logging, and result formatting.
"""

from dataclasses import dataclass
from typing import Any

from src.agents.notifications.trade_command_parser import TradeCommandIntent, parse_trade_command
from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.ticker_utils import resolve_ticker_to_t212

logger = get_logger("command_gateway")


@dataclass(slots=True)
class CommandRequest:
    """Represents an inbound chat command request."""

    source: str
    user_id: str
    channel_id: str | None
    command: str
    args: list[str]
    raw_payload: dict[str, Any]


class CommandGatewayDisabledError(RuntimeError):
    """Raised when inbound command gateway is disabled by config."""


class CommandGateway:
    """Inbound command gateway — routes parsed commands to single-ticker pipeline."""

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.slack_trade_commands_enabled

    def resolve_request(self, request: CommandRequest) -> dict[str, Any]:
        """Parse and resolve an inbound command without running the pipeline."""
        if not self.enabled:
            raise CommandGatewayDisabledError("Command gateway is disabled in configuration")

        text = request.raw_payload.get("text", "") or request.command

        intent = parse_trade_command(text, use_llm_fallback=True)
        if not intent:
            return {"status": "unparseable", "message": "Could not parse trade command."}

        ticker_t212 = resolve_ticker_to_t212(intent.ticker)
        if not ticker_t212:
            return {
                "status": "unknown_ticker",
                "ticker": intent.ticker,
                "message": f"Unknown ticker: {intent.ticker}. Check the symbol and try again.",
            }

        return {
            "status": "ok",
            "intent": intent,
            "ticker_t212": ticker_t212,
            "text": text,
        }

    def handle(self, request: CommandRequest) -> dict[str, Any]:
        """Route an inbound command to the appropriate handler.

        Returns a result dict with at minimum a 'status' key.
        """
        resolved = self.resolve_request(request)
        if resolved.get("status") != "ok":
            return resolved

        intent = resolved["intent"]
        ticker_t212 = resolved["ticker_t212"]
        thread_ts = request.raw_payload.get("thread_ts") or request.raw_payload.get("ts", "")

        from src.orchestrator.single_ticker_run import SingleTickerRunner

        runner = SingleTickerRunner(dry_run=False)
        try:
            result = runner.run(
                ticker_t212=ticker_t212,
                intent=intent,
                user_id=request.user_id,
                channel_id=request.channel_id,
                thread_ts=thread_ts,
            )
            resp: dict[str, Any] = {
                "status": result.status,
                "result": result,
                "intent": intent,
                "ticker_t212": ticker_t212,
            }
            # Propagate error/rejection messages so the listener can display them
            if result.error_message:
                resp["message"] = result.error_message
            elif result.rejection_reason:
                resp["message"] = result.rejection_reason
            return resp
        except Exception as e:
            logger.error(f"Command gateway pipeline error: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
        finally:
            runner.close()
