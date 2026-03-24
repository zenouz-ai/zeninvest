"""Inbound command gateway for ChatOps trade controls (US-1.6).

Routes parsed commands to the single-ticker pipeline. Handles ticker resolution,
command logging, and result formatting.
"""

from dataclasses import dataclass
import re
from typing import Any

from src.agents.notifications.trade_command_parser import _strip_force_prefix
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

    def _extract_subject_phrase(self, text: str) -> str:
        """Extract the user-typed subject phrase after BUY/SELL/REVIEW."""
        cleaned, _ = _strip_force_prefix(text or "")
        cleaned = cleaned.strip()
        cleaned = re.sub(r"^\s*(BUY|SELL|REVIEW)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"^(?:[£$]\d+(?:\.\d+)?\s+(?:of\s+|worth\s+(?:of\s+)?)?)",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^(?:\d+(?:\.\d+)?\s+(?:shares?\s+(?:of\s+)?)?)",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+[£$]\d+(?:\.\d+)?\s*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+\d+(?:\.\d+)?\s*$", "", cleaned, flags=re.IGNORECASE)
        return " ".join(cleaned.split()).strip()

    def _unknown_ticker_message(self, intent: TradeCommandIntent, text: str) -> str:
        """Build a contextual unknown-ticker reply from the original user input."""
        action = intent.action.upper()
        subject_phrase = self._extract_subject_phrase(text)
        if subject_phrase and " " in subject_phrase:
            return (
                f"Unknown ticker: {intent.ticker}. Check the symbol and try again. "
                f"Tip: try the company name directly, for example `{action} {subject_phrase}`."
            )
        return (
            f"Unknown ticker: {intent.ticker}. Check the symbol and try again. "
            "Tip: try the company name instead, for example `REVIEW Rocket Lab`."
        )

    def _unparseable_message(self, text: str) -> str:
        """Build a helpful reply for unsupported conversational requests."""
        normalized = " ".join((text or "").strip().lower().split())
        examples = (
            "Currently supported one-ticker commands include "
            "`BUY AAPL`, `SELL 10 TSLA`, `REVIEW MSFT`, `BUY £500 NVDA`, and "
            "`force sell TSLA`."
        )

        portfolio_keywords = (
            "liquidate",
            "all tickers",
            "all holdings",
            "portfolio",
            "holdings below",
            "holding below",
            "below £",
            "under £",
        )
        if any(keyword in normalized for keyword in portfolio_keywords):
            return (
                "I couldn't action that yet. The current Slack trade listener only supports "
                "one ticker per message, so portfolio-wide rules like "
                "`liquidate all tickers with holding below £100` are not supported yet. "
                f"{examples}"
            )

        return f"I couldn't parse that trade command. {examples}"

    def resolve_request(self, request: CommandRequest) -> dict[str, Any]:
        """Parse and resolve an inbound command without running the pipeline."""
        if not self.enabled:
            raise CommandGatewayDisabledError("Command gateway is disabled in configuration")

        text = request.raw_payload.get("text", "") or request.command

        intent = parse_trade_command(text, use_llm_fallback=True)
        if not intent:
            return {"status": "unparseable", "message": self._unparseable_message(text)}

        ticker_t212 = resolve_ticker_to_t212(intent.ticker)
        if not ticker_t212:
            return {
                "status": "unknown_ticker",
                "ticker": intent.ticker,
                "message": self._unknown_ticker_message(intent, text),
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
