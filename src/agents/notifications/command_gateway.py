"""Inbound command gateway for ChatOps trade controls (US-1.6).

Routes parsed Slack commands to the appropriate execution path:
- strategy review / strategy-triggered trade
- direct trade
- cancel pending orders
"""

from dataclasses import dataclass
import re
from typing import Any

from src.agents.notifications.cancel_command_runner import CancelCommandRunner
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
    """Inbound command gateway that resolves and dispatches Slack trade commands."""

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.slack_trade_commands_enabled

    def _extract_subject_phrase(self, text: str) -> str:
        """Extract the user-typed subject phrase after the leading command."""
        cleaned, _ = _strip_force_prefix(text or "")
        cleaned = cleaned.strip()
        cleaned = re.sub(
            r"^\s*(CANCEL\s+STOP\s+SELL|CANCEL\s+BUY|CANCEL\s+SELL|BUY|SELL|REVIEW)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
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
            "Currently supported commands include "
            "`BUY AAPL`, `SELL 10 TSLA`, `REVIEW MSFT`, `BUY £500 NVDA`, "
            "`buy Apple and trigger strategy`, `review Apple and buy`, and "
            "`cancel stop sell NVDA, Microsoft`."
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

    def _resolve_subjects(self, intent: TradeCommandIntent) -> tuple[list[str], str | None]:
        resolved: list[str] = []
        raw_subjects = getattr(intent, "subject_phrases", None)
        subjects: list[str] = []
        if isinstance(raw_subjects, (list, tuple)):
            subjects = [str(subject).strip() for subject in raw_subjects if str(subject).strip()]
        elif isinstance(raw_subjects, str) and raw_subjects.strip():
            subjects = [raw_subjects.strip()]

        ticker = str(getattr(intent, "ticker", "") or "").strip()
        if not subjects and ticker:
            subjects = [ticker]

        for subject in subjects:
            ticker_t212 = resolve_ticker_to_t212(subject)
            if not ticker_t212:
                return [], subject
            resolved.append(ticker_t212)
        return resolved, None

    def resolve_request(self, request: CommandRequest) -> dict[str, Any]:
        """Parse and resolve an inbound command without running the pipeline."""
        if not self.enabled:
            raise CommandGatewayDisabledError("Command gateway is disabled in configuration")

        text = request.raw_payload.get("text", "") or request.command

        intent = parse_trade_command(text, use_llm_fallback=True)
        if not intent:
            return {"status": "unparseable", "message": self._unparseable_message(text)}

        resolved_tickers, unknown_subject = self._resolve_subjects(intent)
        if unknown_subject:
            return {
                "status": "unknown_ticker",
                "ticker": unknown_subject.upper(),
                "message": self._unknown_ticker_message(intent, text),
            }

        resolved: dict[str, Any] = {
            "status": "ok",
            "intent": intent,
            "text": text,
        }
        command_kind = str(getattr(intent, "command_kind", "trade") or "trade").lower()
        if command_kind == "cancel":
            resolved["ticker_t212s"] = resolved_tickers
        else:
            resolved["ticker_t212"] = resolved_tickers[0]
        return resolved

    def handle(self, request: CommandRequest) -> dict[str, Any]:
        """Route an inbound command to the appropriate handler.

        Returns a result dict with at minimum a 'status' key.
        """
        resolved = self.resolve_request(request)
        if resolved.get("status") != "ok":
            return resolved

        intent = resolved["intent"]
        thread_ts = request.raw_payload.get("thread_ts") or request.raw_payload.get("ts", "")

        try:
            command_kind = str(getattr(intent, "command_kind", "trade") or "trade").lower()
            execution_mode = str(getattr(intent, "execution_mode", "strategy") or "strategy").lower()

            if command_kind == "cancel":
                runner = CancelCommandRunner(dry_run=False)
                try:
                    result = runner.run(
                        ticker_t212s=resolved["ticker_t212s"],
                        intent=intent,
                        user_id=request.user_id,
                        channel_id=request.channel_id,
                        thread_ts=thread_ts,
                    )
                    resp: dict[str, Any] = {
                        "status": result.status,
                        "result": result,
                        "intent": intent,
                        "ticker_t212s": resolved["ticker_t212s"],
                    }
                finally:
                    runner.close()
            else:
                if execution_mode == "strategy":
                    from src.orchestrator.single_ticker_run import SingleTickerRunner

                    runner = SingleTickerRunner(dry_run=False)
                else:
                    from src.orchestrator.direct_trade_run import DirectTradeRunner

                    runner = DirectTradeRunner(dry_run=False)

                try:
                    result = runner.run(
                        ticker_t212=resolved["ticker_t212"],
                        intent=intent,
                        user_id=request.user_id,
                        channel_id=request.channel_id,
                        thread_ts=thread_ts,
                    )
                    resp = {
                        "status": result.status,
                        "result": result,
                        "intent": intent,
                        "ticker_t212": resolved["ticker_t212"],
                    }
                finally:
                    runner.close()

            if result.error_message:
                resp["message"] = result.error_message
            elif result.rejection_reason:
                resp["message"] = result.rejection_reason
            return resp
        except Exception as e:
            logger.error(f"Command gateway pipeline error: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
