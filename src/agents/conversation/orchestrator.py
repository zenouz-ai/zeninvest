"""Conversation orchestration for US-1.9 conversational trading workflow."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from src.agents.execution.order_manager import OrderManager
from src.agents.market_data.data_fetcher import DataFetcher
from src.agents.notifications.cancel_command_runner import CancelCommandRunner
from src.agents.notifications.formatters import format_trade_command_reply
from src.agents.notifications.trade_command_parser import TradeCommandIntent, parse_trade_command
from src.agents.conversation.session_manager import (
    ChatActionNotFoundError,
    ChatSessionNotFoundError,
    SessionManager,
)
from src.data.database import get_session
from src.data.models import ChatAction, Instrument, PortfolioSnapshot
from src.orchestrator.direct_trade_run import DirectTradeRunner
from src.orchestrator.single_ticker_run import PreparedTradeExecution, SingleTickerResult, SingleTickerRunner
from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.ticker_utils import resolve_ticker_to_t212, t212_to_yf

logger = get_logger("conversation_orchestrator")

try:
    from dashboard.backend.app.services.event_logger import log_event
except ImportError:  # pragma: no cover - dashboard import is optional in some environments
    log_event = None


STOP_UPDATE_RE = re.compile(
    r"^\s*(?:set|update|move|raise|lower)\s+(?:the\s+)?stop(?:-loss)?(?:\s+(?:for|on))?\s+"
    r"(?P<subject>.+?)\s+(?:to|at)\s+\$?(?P<price>\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)
COMPARE_RE = re.compile(
    r"^\s*(?:compare|contrast)\s+(?P<left>.+?)\s+(?:and|vs\.?|versus)\s+(?P<right>.+?)\s*$",
    re.IGNORECASE,
)
PORTFOLIO_VALUE_RE = re.compile(
    r"^\s*(?:liquidate|sell)\s+(?:all\s+)?(?:tickers|holdings|positions)\s+(?:with\s+)?(?:holding\s+|value\s+)?"
    r"(?:below|under)\s+[£$]?(?P<threshold>\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)
PORTFOLIO_PNL_RE = re.compile(
    r"^\s*(?:liquidate|sell)\s+(?:all\s+)?(?P<bucket>winners|losers)\s+"
    r"(?:(?:above|over|below|under|worse\s+than|better\s+than)\s+)?(?P<threshold>-?\d+(?:\.\d+)?)%?\s*$",
    re.IGNORECASE,
)
CONFIRM_WORDS = {"yes", "y", "confirm", "approved", "do it", "go ahead"}
REJECT_WORDS = {"no", "n", "reject", "cancel", "stop"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dumps(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _clean_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_json(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


class ConversationOrchestrator:
    """Channel-agnostic conversational workflow for Slack and dashboard chat."""

    def __init__(
        self,
        *,
        session_manager: SessionManager | None = None,
        data_fetcher: DataFetcher | None = None,
        order_manager: OrderManager | None = None,
    ) -> None:
        self.settings = get_settings()
        self.session_manager = session_manager or SessionManager()
        self._data_fetcher = data_fetcher
        self._order_manager = order_manager

    @property
    def data_fetcher(self) -> DataFetcher:
        if self._data_fetcher is None:
            self._data_fetcher = DataFetcher()
        return self._data_fetcher

    @property
    def order_manager(self) -> OrderManager:
        if self._order_manager is None:
            self._order_manager = OrderManager(dry_run=False)
        return self._order_manager

    def start_session(
        self,
        *,
        channel_type: str,
        user_id: str | None = None,
        channel_session_key: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        session_id = self.session_manager.create_session(
            channel_type=channel_type,
            user_id=user_id,
            channel_session_key=channel_session_key,
            title=title,
            resume_if_exists=True,
        )
        self._emit_event(
            "chat_session_updated",
            f"Conversation session {session_id} opened",
            session_id=session_id,
            channel_type=channel_type,
        )
        detail = self.session_manager.get_session(session_id)
        if detail is None:
            raise ChatSessionNotFoundError(f"Chat session {session_id} not found")
        return detail

    def list_sessions(self, *, limit: int | None = None, status: str | None = None) -> list[dict[str, Any]]:
        return self.session_manager.list_sessions(
            limit=limit or self.settings.conversation_max_session_list_size,
            status=status,
        )

    def process_turn(
        self,
        *,
        session_id: int,
        message_text: str,
        channel_type: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        message_text = _clean_text(message_text)
        if not message_text:
            raise ValueError("Message text cannot be empty")

        self.session_manager.expire_old_pending_actions()
        user_turn_id = self.session_manager.add_turn(
            session_id,
            role="user",
            message_text=message_text,
            channel_type=channel_type,
        )
        self._emit_event(
            "chat_turn_created",
            f"User turn received for session {session_id}",
            session_id=session_id,
            turn_id=user_turn_id,
            channel_type=channel_type,
            role="user",
        )

        try:
            session_detail = self.session_manager.get_session(session_id)
            if session_detail is None:
                raise ChatSessionNotFoundError(f"Chat session {session_id} not found")
            context = session_detail.get("context_json") or {}
            if not isinstance(context, dict):
                context = {}

            pending_action = self.session_manager.get_pending_action(session_id)
            normalized = message_text.lower().strip()
            if pending_action and normalized in CONFIRM_WORDS:
                return self.confirm_action(session_id=session_id, action_id=pending_action["id"], channel_type=channel_type)
            if pending_action and normalized in REJECT_WORDS:
                return self.reject_action(session_id=session_id, action_id=pending_action["id"], channel_type=channel_type)

            intent = self._classify_intent(message_text, context)
            result = self._handle_intent(
                session_id=session_id,
                turn_id=user_turn_id,
                message_text=message_text,
                intent=intent,
                context=context,
                channel_type=channel_type,
                user_id=user_id,
            )

            self.session_manager.add_turn(
                session_id,
                role="assistant",
                message_text=result["assistant_text"],
                response_json=result.get("response_json"),
                channel_type=channel_type,
            )
            next_context = result.get("context_update")
            if isinstance(next_context, dict):
                merged = dict(context)
                merged.update(next_context)
                self.session_manager.update_session_context(
                    session_id,
                    context_json=merged,
                    title=merged.get("title"),
                    last_channel_type=channel_type,
                )
            self._emit_event(
                "chat_turn_created",
                f"Assistant turn created for session {session_id}",
                session_id=session_id,
                channel_type=channel_type,
                role="assistant",
            )
            return self._require_session(session_id)
        except Exception as exc:
            logger.error("Conversation turn failed for session %s: %s", session_id, exc, exc_info=True)
            error_text = f"I couldn't complete that request: {exc}"
            self.session_manager.add_turn(
                session_id,
                role="assistant",
                message_text=error_text,
                response_json={"error": str(exc)},
                channel_type=channel_type,
            )
            return self._require_session(session_id)

    def confirm_action(self, *, session_id: int, action_id: int, channel_type: str) -> dict[str, Any]:
        action = self._get_action_for_session(session_id, action_id)
        if action["status"] == "expired":
            self._record_assistant_message(session_id, "Confirmation expired. Please submit the request again.", channel_type)
            return self._require_session(session_id)
        if action["status"] != "awaiting_confirmation":
            self._record_assistant_message(
                session_id,
                f"Action {action_id} is not awaiting confirmation.",
                channel_type,
            )
            return self._require_session(session_id)

        self.session_manager.update_action(
            action_id,
            status="confirmed",
            confirmed_at=_utcnow(),
        )
        self._emit_event(
            "chat_action_updated",
            f"Action {action_id} confirmed",
            session_id=session_id,
            action_id=action_id,
            status="confirmed",
        )

        assistant_text = self._execute_action(action, channel_type=channel_type)
        self._record_assistant_message(session_id, assistant_text, channel_type)
        return self._require_session(session_id)

    def reject_action(self, *, session_id: int, action_id: int, channel_type: str) -> dict[str, Any]:
        action = self._get_action_for_session(session_id, action_id)
        self.session_manager.update_action(
            action_id,
            status="rejected",
            rejection_reason="Cancelled by operator.",
        )
        self._emit_event(
            "chat_action_updated",
            f"Action {action_id} rejected",
            session_id=session_id,
            action_id=action_id,
            status="rejected",
        )
        self._record_assistant_message(session_id, "Action cancelled.", channel_type)
        return self._require_session(session_id)

    def close(self) -> None:
        try:
            self.data_fetcher.close()
        except Exception:
            pass
        try:
            self.order_manager.close()
        except Exception:
            pass

    def _classify_intent(self, message_text: str, context: dict[str, Any]) -> dict[str, Any]:
        trade_intent = parse_trade_command(message_text, use_llm_fallback=False)
        if trade_intent is not None:
            resolved_subjects = self._resolve_subjects(trade_intent.subject_phrases, context)
            trade_intent.subject_phrases = resolved_subjects
            trade_intent.ticker = (resolved_subjects[0].upper() if resolved_subjects else trade_intent.ticker)
            return {"kind": "trade_command", "intent": trade_intent}

        stop_match = STOP_UPDATE_RE.match(message_text)
        if stop_match:
            subject = self._resolve_subject(stop_match.group("subject"), context)
            return {
                "kind": "update_stop",
                "subject": subject,
                "stop_price": float(stop_match.group("price")),
            }

        compare_match = COMPARE_RE.match(message_text)
        if compare_match:
            subjects = self._resolve_subjects(
                [compare_match.group("left"), compare_match.group("right")],
                context,
            )
            return {"kind": "research", "subjects": subjects, "mode": "compare"}

        portfolio_match = PORTFOLIO_VALUE_RE.match(message_text)
        if portfolio_match:
            return {
                "kind": "portfolio_rule",
                "rule": "value_below",
                "threshold": float(portfolio_match.group("threshold")),
            }

        pnl_match = PORTFOLIO_PNL_RE.match(message_text)
        if pnl_match:
            bucket = pnl_match.group("bucket").lower()
            threshold = float(pnl_match.group("threshold"))
            if bucket == "losers" and threshold > 0:
                threshold = -threshold
            if bucket == "winners" and threshold < 0:
                threshold = abs(threshold)
            return {
                "kind": "portfolio_rule",
                "rule": "pnl_threshold",
                "bucket": bucket,
                "threshold": threshold,
            }

        subjects = self._extract_subjects_for_research(message_text, context)
        if subjects:
            return {"kind": "research", "subjects": subjects, "mode": "analysis"}

        return {"kind": "clarify"}

    def _handle_intent(
        self,
        *,
        session_id: int,
        turn_id: int,
        message_text: str,
        intent: dict[str, Any],
        context: dict[str, Any],
        channel_type: str,
        user_id: str | None,
    ) -> dict[str, Any]:
        kind = intent["kind"]
        if kind == "trade_command":
            return self._handle_trade_command(
                session_id=session_id,
                turn_id=turn_id,
                intent=intent["intent"],
                channel_type=channel_type,
                user_id=user_id,
                context=context,
            )
        if kind == "update_stop":
            return self._handle_stop_update(
                session_id=session_id,
                turn_id=turn_id,
                subject=intent["subject"],
                stop_price=float(intent["stop_price"]),
                channel_type=channel_type,
                context=context,
            )
        if kind == "portfolio_rule":
            return self._handle_portfolio_rule(
                session_id=session_id,
                turn_id=turn_id,
                payload=intent,
                channel_type=channel_type,
                context=context,
            )
        if kind == "research":
            return self._handle_research_request(
                session_id=session_id,
                turn_id=turn_id,
                subjects=intent["subjects"],
                mode=intent["mode"],
                context=context,
            )
        return {
            "assistant_text": (
                "I can help with research, single-ticker direct trades, strategy-backed trades, "
                "stop updates, cancel requests, and portfolio rules like `liquidate holdings below £100`. "
                "If you want execution, ask explicitly and I will preview the action before anything runs."
            ),
            "context_update": context,
            "response_json": {"kind": "clarification"},
        }

    def _handle_trade_command(
        self,
        *,
        session_id: int,
        turn_id: int,
        intent: TradeCommandIntent,
        channel_type: str,
        user_id: str | None,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if not intent.subject_phrases:
            return {
                "assistant_text": "I couldn't resolve the ticker from that request. Name the ticker or company explicitly.",
                "context_update": context,
            }

        resolved = [resolve_ticker_to_t212(subject) for subject in intent.subject_phrases]
        if any(ticker is None for ticker in resolved):
            missing = [
                subject
                for subject, ticker in zip(intent.subject_phrases, resolved, strict=False)
                if ticker is None
            ]
            return {
                "assistant_text": f"I couldn't resolve these names to tickers: {', '.join(missing)}.",
                "context_update": context,
            }

        tickers = [str(ticker) for ticker in resolved if ticker]
        if intent.command_kind == "cancel":
            preview = self._preview_cancel_orders(tickers=tickers, order_class=intent.cancel_order_class or "")
            if not preview["matches"]:
                return {
                    "assistant_text": "I found no matching pending orders to cancel.",
                    "context_update": {
                        "last_subject_tickers": tickers,
                        "last_selection_tickers": [],
                    },
                    "response_json": preview,
                }
            action = self.session_manager.create_action(
                session_id=session_id,
                turn_id=turn_id,
                action_type="cancel_orders",
                status="awaiting_confirmation",
                title=f"Cancel pending {intent.cancel_order_class.replace('_', ' ')} orders",
                ticker=tickers[0],
                payload_json={
                    "tickers": tickers,
                    "order_class": intent.cancel_order_class,
                    "raw_message": intent.raw_message,
                },
                preview_text=preview["preview_text"],
                requires_confirmation=True,
                expires_at=_utcnow() + timedelta(minutes=self.settings.conversation_confirmation_timeout_minutes),
            )
            self._emit_event(
                "chat_action_proposed",
                f"Cancel proposal created for session {session_id}",
                session_id=session_id,
                action_id=action["id"],
                status=action["status"],
            )
            return {
                "assistant_text": preview["preview_text"],
                "context_update": {
                    "last_subject_tickers": tickers,
                    "last_selection_tickers": tickers,
                },
                "response_json": action,
            }

        ticker_t212 = tickers[0]
        if intent.command_kind == "review" or intent.action == "REVIEW":
            runner = SingleTickerRunner(dry_run=False)
            try:
                result = runner.prepare(
                    ticker_t212=ticker_t212,
                    intent=intent,
                    user_id=user_id,
                    channel_id=None,
                    thread_ts=None,
                    log_command=False,
                )
                text = format_trade_command_reply(result)
            finally:
                runner.close()
            self.session_manager.add_research_log(
                session_id=session_id,
                turn_id=turn_id,
                tool_name="strategy_review",
                provider="strategy_pipeline",
                query=ticker_t212,
                result_summary=text[:500],
            )
            return {
                "assistant_text": text,
                "context_update": {
                    "last_subject_tickers": [ticker_t212],
                    "last_selection_tickers": [ticker_t212],
                },
                "response_json": {"kind": "review", "ticker": ticker_t212},
            }

        runner: Any
        if intent.execution_mode == "strategy":
            runner = SingleTickerRunner(dry_run=False)
        else:
            runner = DirectTradeRunner(dry_run=False)

        try:
            result = runner.prepare(
                ticker_t212=ticker_t212,
                intent=intent,
                user_id=user_id,
                channel_id=None,
                thread_ts=None,
                log_command=False,
            )
        finally:
            runner.close()

        if result.status != "ready":
            text = format_trade_command_reply(result)
            action = self.session_manager.create_action(
                session_id=session_id,
                turn_id=turn_id,
                action_type=f"{intent.execution_mode}_trade",
                status="rejected" if result.status == "rejected" else "failed",
                title=f"{intent.action} {ticker_t212}",
                ticker=ticker_t212,
                payload_json=self._serialize_single_ticker_result(result),
                preview_text=text,
                result_json=self._serialize_single_ticker_result(result),
                requires_confirmation=False,
                rejection_reason=result.rejection_reason or result.error_message,
            )
            self._emit_event(
                "chat_action_updated",
                f"Trade request rejected for session {session_id}",
                session_id=session_id,
                action_id=action["id"],
                status=action["status"],
            )
            return {
                "assistant_text": text,
                "context_update": {
                    "last_subject_tickers": [ticker_t212],
                    "last_selection_tickers": [ticker_t212],
                },
                "response_json": action,
            }

        preview_text = self._format_trade_preview(result)
        action = self.session_manager.create_action(
            session_id=session_id,
            turn_id=turn_id,
            action_type=f"{intent.execution_mode}_trade",
            status="awaiting_confirmation",
            title=f"{intent.action} {ticker_t212}",
            ticker=ticker_t212,
            payload_json=self._serialize_single_ticker_result(result),
            preview_text=preview_text,
            requires_confirmation=True,
            expires_at=_utcnow() + timedelta(minutes=self.settings.conversation_confirmation_timeout_minutes),
        )
        self._emit_event(
            "chat_action_proposed",
            f"Trade proposal created for session {session_id}",
            session_id=session_id,
            action_id=action["id"],
            status=action["status"],
        )
        return {
            "assistant_text": preview_text,
            "context_update": {
                "last_subject_tickers": [ticker_t212],
                "last_selection_tickers": [ticker_t212],
            },
            "response_json": action,
        }

    def _handle_stop_update(
        self,
        *,
        session_id: int,
        turn_id: int,
        subject: str,
        stop_price: float,
        channel_type: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        ticker = resolve_ticker_to_t212(subject)
        if not ticker:
            return {
                "assistant_text": f"I couldn't resolve `{subject}` to a ticker for the stop update.",
                "context_update": context,
            }

        position = self.order_manager.client.get_position(ticker)
        quantity = float(position.get("quantity", 0) or 0)
        current_price = float(position.get("currentPrice", 0) or 0)
        if quantity <= 0:
            return {
                "assistant_text": f"There is no open position in {ticker} to protect with a stop.",
                "context_update": {
                    "last_subject_tickers": [ticker],
                },
            }
        if current_price <= 0:
            return {
                "assistant_text": f"I couldn't determine the current price for {ticker}.",
                "context_update": {
                    "last_subject_tickers": [ticker],
                },
            }
        if stop_price >= current_price:
            return {
                "assistant_text": (
                    f"The requested stop price ${stop_price:.2f} must remain below the current price "
                    f"(${current_price:.2f}) for {ticker}."
                ),
                "context_update": {
                    "last_subject_tickers": [ticker],
                },
            }

        preview_text = (
            f"Proposed stop update for {ticker}: move protective stop to ${stop_price:.2f} "
            f"for {quantity:.2f} shares. Reply or confirm to execute."
        )
        action = self.session_manager.create_action(
            session_id=session_id,
            turn_id=turn_id,
            action_type="update_stop",
            status="awaiting_confirmation",
            title=f"Update stop for {ticker}",
            ticker=ticker,
            payload_json={
                "ticker": ticker,
                "stop_price": stop_price,
                "quantity": quantity,
                "current_price": current_price,
            },
            preview_text=preview_text,
            requires_confirmation=True,
            expires_at=_utcnow() + timedelta(minutes=self.settings.conversation_confirmation_timeout_minutes),
        )
        self._emit_event(
            "chat_action_proposed",
            f"Stop update proposed for session {session_id}",
            session_id=session_id,
            action_id=action["id"],
            status=action["status"],
        )
        return {
            "assistant_text": preview_text,
            "context_update": {
                "last_subject_tickers": [ticker],
                "last_selection_tickers": [ticker],
            },
            "response_json": action,
        }

    def _handle_portfolio_rule(
        self,
        *,
        session_id: int,
        turn_id: int,
        payload: dict[str, Any],
        channel_type: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        positions = self._get_portfolio_positions()
        if payload["rule"] == "value_below":
            threshold = float(payload["threshold"])
            matches = [pos for pos in positions if float(pos.get("value_gbp", 0) or 0) < threshold]
            title = f"Liquidate holdings below £{threshold:.2f}"
        else:
            threshold = float(payload["threshold"])
            bucket = payload["bucket"]
            if bucket == "winners":
                matches = [pos for pos in positions if float(pos.get("pnl_pct", 0) or 0) >= threshold]
                title = f"Sell winners above {threshold:.1f}%"
            else:
                matches = [pos for pos in positions if float(pos.get("pnl_pct", 0) or 0) <= threshold]
                title = f"Sell losers below {threshold:.1f}%"

        if not matches:
            return {
                "assistant_text": "No current holdings match that portfolio rule.",
                "context_update": context,
                "response_json": {"matches": []},
            }

        tickers = [pos["ticker"] for pos in matches]
        preview_lines = [title, "Matches:"]
        for pos in matches[:10]:
            preview_lines.append(
                f"- {pos['ticker']}: value £{pos['value_gbp']:.2f} | P&L {pos['pnl_pct']:+.1f}%"
            )
        if len(matches) > 10:
            preview_lines.append(f"- ...and {len(matches) - 10} more")
        preview_lines.append("Confirm to execute the batch sell. Each position will be handled independently.")
        preview_text = "\n".join(preview_lines)

        action = self.session_manager.create_action(
            session_id=session_id,
            turn_id=turn_id,
            action_type="portfolio_batch_sell",
            status="awaiting_confirmation",
            title=title,
            ticker=tickers[0],
            payload_json={
                "rule": payload,
                "positions": matches,
                "tickers": tickers,
            },
            preview_text=preview_text,
            requires_confirmation=True,
            expires_at=_utcnow() + timedelta(minutes=self.settings.conversation_confirmation_timeout_minutes),
        )
        self._emit_event(
            "chat_action_proposed",
            f"Portfolio batch sell proposed for session {session_id}",
            session_id=session_id,
            action_id=action["id"],
            status=action["status"],
        )
        return {
            "assistant_text": preview_text,
            "context_update": {
                "last_subject_tickers": tickers,
                "last_selection_tickers": tickers,
            },
            "response_json": action,
        }

    def _handle_research_request(
        self,
        *,
        session_id: int,
        turn_id: int,
        subjects: list[str],
        mode: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        tickers = [resolve_ticker_to_t212(subject) for subject in subjects]
        tickers = [ticker for ticker in tickers if ticker]
        if not tickers and context.get("last_subject_tickers"):
            tickers = [ticker for ticker in context["last_subject_tickers"] if ticker]
        if not tickers:
            return {
                "assistant_text": "I need at least one ticker or company name to analyze.",
                "context_update": context,
            }

        lines: list[str] = []
        for ticker in tickers[:3]:
            text, summary = self._build_research_summary(ticker)
            lines.append(text)
            self.session_manager.add_research_log(
                session_id=session_id,
                turn_id=turn_id,
                tool_name="lite_analysis",
                provider="yfinance",
                query=ticker,
                result_summary=summary,
            )

        if mode == "compare" and len(lines) >= 2:
            header = "Comparison"
        else:
            header = "Research summary"
        return {
            "assistant_text": f"{header}\n\n" + "\n\n".join(lines),
            "context_update": {
                "last_subject_tickers": tickers,
                "last_selection_tickers": tickers,
            },
            "response_json": {"kind": "research", "tickers": tickers},
        }

    def _execute_action(self, action: dict[str, Any], *, channel_type: str) -> str:
        action_id = int(action["id"])
        action_type = str(action["action_type"])
        payload = action.get("payload_json") or {}
        self.session_manager.update_action(action_id, status="executing")

        if action_type in {"strategy_trade", "direct_trade"}:
            prepared = self._deserialize_single_ticker_result(payload)
            if prepared.execution_mode == "strategy":
                runner: Any = SingleTickerRunner(dry_run=False)
            else:
                runner = DirectTradeRunner(dry_run=False)
            try:
                final_result = runner.execute_prepared(prepared)
            finally:
                runner.close()
            reply = format_trade_command_reply(final_result)
            final_status = "executed" if final_result.status == "executed" else ("rejected" if final_result.status == "rejected" else "failed")
            self.session_manager.update_action(
                action_id,
                status=final_status,
                result_json=self._serialize_single_ticker_result(final_result),
                rejection_reason=final_result.rejection_reason or final_result.error_message,
                executed_at=_utcnow(),
            )
            self._emit_event(
                "chat_execution_completed",
                f"Trade execution completed for action {action_id}",
                action_id=action_id,
                session_id=action["session_id"],
                status=final_status,
                channel_type=channel_type,
            )
            return reply

        if action_type == "cancel_orders":
            cancel_intent = TradeCommandIntent(
                action="CANCEL",
                ticker=str((payload.get("tickers") or [""])[0]),
                raw_message=str(payload.get("raw_message") or ""),
                command_kind="cancel",
                execution_mode="cancel_only",
                cancel_order_class=str(payload.get("order_class") or ""),
                subject_phrases=list(payload.get("tickers") or []),
            )
            runner = CancelCommandRunner(dry_run=False)
            try:
                result = runner.run(
                    ticker_t212s=list(payload.get("tickers") or []),
                    intent=cancel_intent,
                    channel_id=None,
                    thread_ts=None,
                    log_command=False,
                )
            finally:
                runner.close()
            reply = format_trade_command_reply(result)
            final_status = "executed" if result.status == "executed" else ("failed" if result.status == "error" else result.status)
            self.session_manager.update_action(
                action_id,
                status=final_status,
                result_json={
                    "result": result.result_details,
                    "status": result.status,
                    "rejection_reason": result.rejection_reason,
                    "error_message": result.error_message,
                },
                rejection_reason=result.rejection_reason or result.error_message,
                executed_at=_utcnow(),
            )
            self._emit_event(
                "chat_execution_completed",
                f"Cancel execution completed for action {action_id}",
                action_id=action_id,
                session_id=action["session_id"],
                status=final_status,
                channel_type=channel_type,
            )
            return reply

        if action_type == "update_stop":
            payload = payload or {}
            ticker = str(payload.get("ticker") or "")
            quantity = float(payload.get("quantity") or 0)
            current_price = float(payload.get("current_price") or 0)
            stop_price = float(payload.get("stop_price") or 0)
            cancel_result = self.order_manager.cancel_conflicting_stops(ticker)
            if cancel_result.get("status") == "failed":
                reply = f"Failed to update stop for {ticker}: {cancel_result.get('error', 'unknown error')}"
                self.session_manager.update_action(
                    action_id,
                    status="failed",
                    result_json=cancel_result,
                    rejection_reason=reply,
                    executed_at=_utcnow(),
                )
                return reply
            stop_loss_pct = -((current_price - stop_price) / current_price * 100)
            stop_result = self.order_manager.place_stop_loss(
                ticker=ticker,
                quantity=quantity,
                current_price=current_price,
                stop_loss_pct=stop_loss_pct,
                strategy="conversation_stop_update",
                current_price_gbp=current_price,
            )
            if stop_result.get("status") in {"filled", "pending", "dry_run"}:
                status = "executed"
                reply = f"Updated stop for {ticker} to ${stop_price:.2f}."
            else:
                status = "failed"
                reply = f"Failed to update stop for {ticker}: {stop_result.get('error') or stop_result.get('reason', 'unknown error')}"
            self.session_manager.update_action(
                action_id,
                status=status,
                result_json=stop_result,
                rejection_reason=None if status == "executed" else reply,
                executed_at=_utcnow(),
            )
            self._emit_event(
                "chat_execution_completed",
                f"Stop update completed for action {action_id}",
                action_id=action_id,
                session_id=action["session_id"],
                status=status,
                channel_type=channel_type,
            )
            return reply

        if action_type == "portfolio_batch_sell":
            positions = list(payload.get("positions") or [])
            results: list[dict[str, Any]] = []
            lines = ["Batch sell result"]
            for pos in positions:
                ticker = str(pos.get("ticker") or "")
                sell_intent = TradeCommandIntent(
                    action="SELL",
                    ticker=ticker,
                    raw_message=f"SELL {ticker}",
                    command_kind="trade",
                    execution_mode="direct",
                    subject_phrases=[ticker],
                )
                runner = DirectTradeRunner(dry_run=False)
                try:
                    prepared = runner.prepare(
                        ticker_t212=ticker,
                        intent=sell_intent,
                        channel_id=None,
                        thread_ts=None,
                        log_command=False,
                    )
                    final_result = prepared if prepared.status != "ready" else runner.execute_prepared(prepared)
                finally:
                    runner.close()
                entry = {
                    "ticker": ticker,
                    "status": final_result.status,
                    "rejection_reason": final_result.rejection_reason,
                    "error_message": final_result.error_message,
                    "value_gbp": pos.get("value_gbp"),
                }
                results.append(entry)
                if final_result.status == "executed":
                    lines.append(f"- {ticker}: executed")
                elif final_result.status == "rejected":
                    lines.append(f"- {ticker}: rejected ({final_result.rejection_reason})")
                else:
                    lines.append(f"- {ticker}: failed ({final_result.error_message})")
            failed = [row for row in results if row["status"] != "executed"]
            status = "executed" if not failed else ("failed" if len(failed) == len(results) else "partial")
            self.session_manager.update_action(
                action_id,
                status=status,
                result_json={"results": results},
                rejection_reason=None if status == "executed" else "Some batch items did not execute.",
                executed_at=_utcnow(),
            )
            self._emit_event(
                "chat_execution_completed",
                f"Portfolio batch execution completed for action {action_id}",
                action_id=action_id,
                session_id=action["session_id"],
                status=status,
                channel_type=channel_type,
            )
            return "\n".join(lines)

        self.session_manager.update_action(
            action_id,
            status="failed",
            rejection_reason=f"Unsupported action type: {action_type}",
            executed_at=_utcnow(),
        )
        return f"Unsupported action type: {action_type}"

    def _record_assistant_message(self, session_id: int, message_text: str, channel_type: str) -> None:
        self.session_manager.add_turn(
            session_id,
            role="assistant",
            message_text=message_text,
            response_json={"message": message_text},
            channel_type=channel_type,
        )

    def _build_research_summary(self, ticker_t212: str) -> tuple[str, str]:
        yf_ticker = t212_to_yf(ticker_t212)
        started = time.monotonic()
        analysis = self.data_fetcher.get_stock_analysis_lite(yf_ticker)
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        indicators = analysis.get("indicators") or {}
        fundamentals = analysis.get("fundamentals") or {}
        session = get_session()
        try:
            instrument = session.query(Instrument).filter(Instrument.ticker == ticker_t212).first()
            company_name = instrument.name if instrument else yf_ticker
            sector = instrument.sector if instrument else None
            business_summary = (instrument.business_summary or "")[:240] if instrument else ""
        finally:
            session.close()

        current_price = _safe_float(indicators.get("current_price")) or _safe_float(analysis.get("current_price")) or 0.0
        rsi = _safe_float(indicators.get("rsi_14"))
        rel = _safe_float(analysis.get("relative_strength_6m"))
        pe = _safe_float(fundamentals.get("trailing_pe"))
        debt = _safe_float(fundamentals.get("debt_equity"))
        volume_ratio = _safe_float(indicators.get("volume_sma_ratio_20"))

        lines = [f"{ticker_t212} ({company_name})"]
        if current_price:
            lines.append(f"- Price: ${current_price:.2f}")
        if sector:
            lines.append(f"- Sector: {sector}")
        if rsi is not None:
            lines.append(f"- RSI(14): {rsi:.1f}")
        if rel is not None:
            lines.append(f"- Relative strength 6m: {rel:.2f}")
        if volume_ratio is not None:
            lines.append(f"- Volume ratio vs 20d avg: {volume_ratio:.2f}x")
        if pe is not None:
            lines.append(f"- Trailing P/E: {pe:.1f}")
        if debt is not None:
            lines.append(f"- Debt/Equity: {debt:.2f}")
        if business_summary:
            lines.append(f"- Profile: {business_summary}")
        lines.append(f"- Analysis latency: {latency_ms:.0f} ms")
        summary = "; ".join(lines[:5])
        return "\n".join(lines), summary

    def _preview_cancel_orders(self, *, tickers: list[str], order_class: str) -> dict[str, Any]:
        live_pending = self.order_manager.client.get_pending_orders()
        matches: list[dict[str, Any]] = []
        for live_order in live_pending:
            ticker = str(live_order.get("ticker") or "")
            if ticker not in tickers:
                continue
            classified = self.order_manager._classify_pending_order(live_order, None)  # noqa: SLF001
            if classified != order_class:
                continue
            matches.append(
                {
                    "order_id": str(live_order.get("id") or live_order.get("orderId") or ""),
                    "ticker": ticker,
                    "classified_as": classified,
                    "type": live_order.get("type"),
                }
            )

        if not matches:
            preview_text = "I found no matching pending orders to cancel."
        else:
            preview_lines = [f"Matched {len(matches)} pending {order_class.replace('_', ' ')} order(s):"]
            for match in matches[:10]:
                preview_lines.append(f"- {match['ticker']} | order {match['order_id']}")
            if len(matches) > 10:
                preview_lines.append(f"- ...and {len(matches) - 10} more")
            preview_lines.append("Confirm to cancel these orders.")
            preview_text = "\n".join(preview_lines)
        return {"matches": matches, "preview_text": preview_text}

    def _get_portfolio_positions(self) -> list[dict[str, Any]]:
        state = self.order_manager.get_portfolio_state()
        positions = state.get("positions") or []
        if positions:
            return [self._normalize_position(pos) for pos in positions if self._normalize_position(pos)]

        session = get_session()
        try:
            snapshot = session.query(PortfolioSnapshot).order_by(PortfolioSnapshot.timestamp.desc()).first()
            if not snapshot or not snapshot.positions_json:
                return []
            raw_positions = _safe_json(snapshot.positions_json) or []
            return [self._normalize_position(pos) for pos in raw_positions if self._normalize_position(pos)]
        finally:
            session.close()

    def _normalize_position(self, pos: dict[str, Any]) -> dict[str, Any] | None:
        ticker = (pos.get("instrument") or {}).get("ticker") or pos.get("ticker")
        if not ticker:
            return None
        quantity = float(pos.get("quantity", 0) or 0)
        wallet = pos.get("walletImpact") or {}
        current_price = float(pos.get("currentPrice", 0) or 0)
        value_gbp = float(pos.get("value_gbp", 0) or 0) or float(wallet.get("currentValue", 0) or 0)
        if not value_gbp and quantity and current_price:
            value_gbp = quantity * current_price
        pnl_gbp = float(pos.get("pnl_gbp", 0) or 0) or float(wallet.get("unrealizedProfitLoss", 0) or 0)
        total_cost = float(wallet.get("totalCost", 0) or 0)
        pnl_pct = float(pos.get("pnl_pct", 0) or 0) or ((pnl_gbp / total_cost * 100) if total_cost else 0.0)
        return {
            "ticker": str(ticker),
            "quantity": quantity,
            "current_price": current_price,
            "value_gbp": float(value_gbp),
            "pnl_gbp": float(pnl_gbp),
            "pnl_pct": float(pnl_pct),
        }

    def _extract_subjects_for_research(self, message_text: str, context: dict[str, Any]) -> list[str]:
        lowered = message_text.lower()
        if any(token in lowered for token in ("what about", "dig deeper", "explain", "research", "look into", "compare", "happening with")):
            if context.get("last_subject_tickers") and any(token in lowered for token in ("that", "those", "it", "them")):
                return list(context["last_subject_tickers"])
            chunks = re.split(r"\band\b|,|vs\.?|versus", message_text, flags=re.IGNORECASE)
            subjects = [self._resolve_subject(chunk, context) for chunk in chunks]
            subjects = [subject for subject in subjects if subject and len(subject.split()) <= 6]
            if subjects:
                return subjects
        return []

    def _resolve_subjects(self, subjects: list[str], context: dict[str, Any]) -> list[str]:
        resolved: list[str] = []
        for subject in subjects:
            value = self._resolve_subject(subject, context)
            if value:
                resolved.append(value)
        return resolved

    def _resolve_subject(self, subject: str, context: dict[str, Any]) -> str:
        cleaned = _clean_text(subject)
        lowered = cleaned.lower()
        last_tickers = list(context.get("last_subject_tickers") or [])
        if lowered in {"the first one", "first one", "first"} and last_tickers:
            return last_tickers[0]
        if lowered in {"the second one", "second one", "second"} and len(last_tickers) > 1:
            return last_tickers[1]
        if lowered in {"that one", "that ticker", "it"} and len(last_tickers) == 1:
            return last_tickers[0]
        if lowered in {"them", "those", "those names"} and last_tickers:
            return last_tickers[0]
        return cleaned

    def _format_trade_preview(self, result: SingleTickerResult) -> str:
        ticker = result.ticker_yf or result.ticker_t212
        mode = "strategy-backed" if result.execution_mode == "strategy" else "direct"
        lines = [f"Proposed {result.user_action} {ticker} ({mode})."]
        if result.quantity and result.price:
            lines.append(f"Estimated size: {result.quantity:.2f} shares at ${result.price:.2f} (about £{result.value_gbp:.2f}).")
        elif result.value_gbp:
            lines.append(f"Estimated value: £{result.value_gbp:.2f}.")
        if result.strategy_decision:
            lines.append(
                f"Strategy: {result.strategy_action or 'N/A'} with conviction {result.conviction} and "
                f"target allocation {result.strategy_decision.get('target_allocation_pct', '—')}%."
            )
        if result.moderation_consensus:
            lines.append(f"Moderation: {result.moderation_consensus}.")
        if result.risk_verdict_str:
            lines.append(f"Risk verdict: {result.risk_verdict_str}.")
        lines.append("Confirm to execute, or reply no/cancel to reject.")
        return "\n".join(lines)

    def _serialize_single_ticker_result(self, result: SingleTickerResult) -> dict[str, Any]:
        payload = asdict(result)
        prepared = payload.get("prepared_execution")
        if prepared is None and result.prepared_execution is not None:
            payload["prepared_execution"] = asdict(result.prepared_execution)
        return payload

    def _deserialize_single_ticker_result(self, payload: dict[str, Any]) -> SingleTickerResult:
        prepared_payload = payload.get("prepared_execution")
        prepared_execution = None
        if isinstance(prepared_payload, dict):
            prepared_execution = PreparedTradeExecution(**prepared_payload)

        result = SingleTickerResult(
            ticker_t212=str(payload.get("ticker_t212") or ""),
            ticker_yf=str(payload.get("ticker_yf") or ""),
            cycle_id=str(payload.get("cycle_id") or ""),
            user_action=str(payload.get("user_action") or ""),
        )
        for key, value in payload.items():
            if key == "prepared_execution":
                continue
            if hasattr(result, key):
                setattr(result, key, value)
        result.prepared_execution = prepared_execution
        return result

    def _require_session(self, session_id: int) -> dict[str, Any]:
        detail = self.session_manager.get_session(session_id)
        if detail is None:
            raise ChatSessionNotFoundError(f"Chat session {session_id} not found")
        return detail

    def _get_action_for_session(self, session_id: int, action_id: int) -> dict[str, Any]:
        detail = self._require_session(session_id)
        for action in detail.get("actions", []):
            if int(action["id"]) == int(action_id):
                return action
        raise ChatActionNotFoundError(f"Chat action {action_id} not found")

    def _emit_event(self, event_type: str, message: str, **metadata: Any) -> None:
        if log_event is None:
            return
        try:
            log_event(
                event_type=event_type,
                source="conversation",
                message=message,
                metadata=metadata,
            )
        except Exception:
            logger.debug("Failed to emit chat event", exc_info=True)
