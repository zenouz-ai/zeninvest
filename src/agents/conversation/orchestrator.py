"""Conversation orchestration for US-1.9 conversational trading workflow."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from src.agents.conversation.compare_parser import (
    CompareRequest,
    parse_compare_request,
    retarget_trade_intent_to_winner,
)
from src.agents.conversation.intent_classifier import (
    ClassifiedIntent,
    IntentClassifier,
    COMMITTEE_SUBJECT_RE,
    CONFIRM_WORDS,
    FOLLOW_UP_CONTEXT_RE,
    PEER_SCAN_HINT_RE,
    PORTFOLIO_VALUE_RE,
    PORTFOLIO_PNL_RE,
    REJECT_WORDS,
    RESEARCH_PREFIX_RE,
    STOP_UPDATE_RE,
    TARGET_SUFFIX_RE,
)
from src.agents.conversation.composer_safety import apply_safety_check
from src.agents.conversation.planner import ChatPlanner, ChatPlannerDecision
from src.agents.execution.order_manager import OrderManager
from src.agents.market_data.data_fetcher import DataFetcher
from src.agents.notifications.cancel_command_runner import CancelCommandRunner
from src.agents.notifications.formatters import format_trade_command_reply
from src.agents.notifications.trade_command_parser import TradeCommandIntent, parse_trade_command
from src.agents.research.executor import ResearchExecutor
from src.agents.conversation.specialists import ChatSpecialistEngine
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
from src.utils.chat_cost_context import bind_chat_cost_context
from src.utils.logger import get_logger
from src.utils.ticker_utils import resolve_ticker_to_t212, t212_to_yf

logger = get_logger("conversation_orchestrator")

try:
    from dashboard.backend.app.services.event_logger import log_event
except ImportError:  # pragma: no cover - dashboard import is optional in some environments
    log_event = None


# Regex constants are now consolidated in intent_classifier.py and imported above.
SLACK_REPLY_MAX_CHARS = 3500


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
        self._slack_web_client: Any | None = None
        self._planner = ChatPlanner()
        self._specialists = ChatSpecialistEngine()
        self._intent_classifier = IntentClassifier()

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
        raw_message_text: str | None = None,
        channel_type: str,
        user_id: str | None = None,
        mode: str | None = None,
        budget_tier: str | None = None,
    ) -> dict[str, Any]:
        message_text = _clean_text(message_text)
        if not message_text:
            raise ValueError("Message text cannot be empty")

        self.session_manager.expire_old_pending_actions()
        user_turn_id = self.session_manager.add_turn(
            session_id,
            role="user",
            message_text=message_text,
            intent_json={
                "requested_mode": mode or self.settings.conversation_default_mode,
                "budget_tier": budget_tier or self.settings.conversation_default_budget_tier,
                "raw_message_text": raw_message_text if raw_message_text and raw_message_text != message_text else None,
            },
            channel_type=channel_type,
        )
        if self.settings.conversation_transparency_enabled:
            received_step = self.session_manager.add_workflow_step(
                session_id=session_id,
                turn_id=user_turn_id,
                step_key="received",
                status="completed",
                label="Received request",
                detail=f"Received {channel_type} message for agentic processing.",
                completed_at=_utcnow(),
                detail_json={
                    "channel_type": channel_type,
                    "requested_mode": mode or self.settings.conversation_default_mode,
                    "budget_tier": budget_tier or self.settings.conversation_default_budget_tier,
                },
            )
            self._emit_workflow_event("chat_step_completed", received_step)
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

            deterministic_intent = self._classify_intent(message_text, context)
            if deterministic_intent["kind"] in {"trade_command", "update_stop", "portfolio_rule"}:
                with bind_chat_cost_context(session_id=session_id, turn_id=user_turn_id):
                    result = self._handle_intent(
                        session_id=session_id,
                        turn_id=user_turn_id,
                        message_text=message_text,
                        intent=deterministic_intent,
                        context=context,
                        channel_type=channel_type,
                        user_id=user_id,
                    )
                    result = self._attach_agentic_metadata(
                        session_id=session_id,
                        turn_id=user_turn_id,
                        result=result,
                        planner_decision=ChatPlannerDecision(
                            route="trade_preview" if deterministic_intent["kind"] == "trade_command" else "quick_answer",
                            turn_mode="trade" if deterministic_intent["kind"] == "trade_command" else "quick",
                            use_fast_path=True,
                            requires_web_research=False,
                            requires_related_scan=False,
                            requires_committee=False,
                            requires_trade_preview=deterministic_intent["kind"] == "trade_command",
                            should_suggest_opportunity=False,
                            confidence=0.95,
                            next_actions=["confirm", "reject"]
                            if deterministic_intent["kind"] == "trade_command"
                            else ["confirm", "reject", "show exposures"],
                            explanation="Deterministic command parser matched the request.",
                            comparison_subjects=[],
                        ),
                        context=context,
                    )
                self.session_manager.add_turn(
                    session_id,
                    role="assistant",
                    message_text=result["assistant_text"],
                    response_json=result.get("response_json"),
                    channel_type=channel_type,
                )
                self._mirror_assistant_reply_to_slack(
                    session_id=session_id,
                    message_text=result["assistant_text"],
                    source_channel_type=channel_type,
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

            planning_step_id: int | None = None
            planner_decision: ChatPlannerDecision | None = None
            if self.settings.conversation_transparency_enabled:
                planning_step = self.session_manager.add_workflow_step(
                    session_id=session_id,
                    turn_id=user_turn_id,
                    step_key="planning",
                    status="running",
                    label="Planning response",
                    detail="Choosing the best route for this turn.",
                    model=self.settings.conversation_planner_model,
                )
                planning_step_id = int(planning_step["id"])
                self._emit_workflow_event("chat_step_started", planning_step)

            planner_decision = self._planner.plan_turn(
                message_text=message_text,
                context=context,
                requested_mode=mode or self.settings.conversation_default_mode,
                budget_tier=budget_tier or self.settings.conversation_default_budget_tier,
            )
            if planning_step_id is not None:
                planning_step = self.session_manager.update_workflow_step(
                    planning_step_id,
                    status="completed",
                    detail=planner_decision.explanation,
                    model=self.settings.conversation_planner_model,
                    cost_gbp=self._cost_delta_for_step(session_id, 0.0),
                    completed_at=_utcnow(),
                    detail_json=planner_decision.as_dict(),
                )
                self._emit_workflow_event("chat_step_completed", planning_step)

            with bind_chat_cost_context(session_id=session_id, turn_id=user_turn_id):
                if planner_decision.use_fast_path:
                    if planner_decision.route == "help_or_explain":
                        result = self._handle_help_or_explain(message_text=message_text, context=context)
                    else:
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
                    result = self._attach_agentic_metadata(
                        session_id=session_id,
                        turn_id=user_turn_id,
                        result=result,
                        planner_decision=planner_decision,
                        context=context,
                    )
                else:
                    result = self._handle_agentic_turn(
                        session_id=session_id,
                        turn_id=user_turn_id,
                        message_text=message_text,
                        context=context,
                        planner_decision=planner_decision,
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
            self._mirror_assistant_reply_to_slack(
                session_id=session_id,
                message_text=result["assistant_text"],
                source_channel_type=channel_type,
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
            if self.settings.conversation_transparency_enabled:
                failed_step = self.session_manager.add_workflow_step(
                    session_id=session_id,
                    turn_id=user_turn_id,
                    step_key="failed",
                    status="failed",
                    label="Turn failed",
                    detail=str(exc),
                    completed_at=_utcnow(),
                )
                self._emit_workflow_event("chat_step_completed", failed_step)
            error_text = f"I couldn't complete that request: {exc}"
            self.session_manager.add_turn(
                session_id,
                role="assistant",
                message_text=error_text,
                response_json={"error": str(exc)},
                channel_type=channel_type,
            )
            self._mirror_assistant_reply_to_slack(
                session_id=session_id,
                message_text=error_text,
                source_channel_type=channel_type,
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
        """Classify user message into a structured intent dict.

        Delegates to IntentClassifier for the three-layer classification,
        then converts the ClassifiedIntent into the legacy dict format
        expected by _handle_intent().
        """
        classified = self._intent_classifier.classify(
            message_text, context,
        )

        # Convert ClassifiedIntent to the legacy dict format used by _handle_intent
        if classified.intent_type in ("trade_command", "cancel", "review"):
            trade_intent = classified.payload.get("trade_intent")
            if trade_intent is not None:
                resolved_subjects = self._resolve_subjects(trade_intent.subject_phrases, context)
                trade_intent.subject_phrases = resolved_subjects
                trade_intent.ticker = (resolved_subjects[0].upper() if resolved_subjects else trade_intent.ticker)
                return {"kind": "trade_command", "intent": trade_intent}

        if classified.intent_type == "update_stop":
            subject = self._resolve_subject(classified.payload.get("subject", ""), context)
            return {
                "kind": "update_stop",
                "subject": subject,
                "stop_price": float(classified.payload.get("stop_price", 0)),
            }

        if classified.intent_type == "portfolio_rule":
            return {"kind": "portfolio_rule", **classified.payload}

        if classified.intent_type == "compare":
            compare_request = classified.payload.get("compare_request")
            if compare_request is not None:
                subjects = self._resolve_subjects(compare_request.subjects, context)
                return {
                    "kind": "research",
                    "subjects": subjects,
                    "mode": "compare",
                    "compare_request": compare_request.as_dict(),
                }
            # Heuristic compare (no structured CompareRequest)
            subjects = self._extract_subjects_for_research(message_text, context)
            if subjects:
                return {"kind": "research", "subjects": subjects, "mode": "compare"}

        if classified.intent_type == "research":
            context_tickers = classified.payload.get("context_tickers")
            if context_tickers:
                return {"kind": "research", "subjects": context_tickers, "mode": "analysis"}
            subjects = self._extract_subjects_for_research(message_text, context)
            if subjects:
                return {"kind": "research", "subjects": subjects, "mode": "analysis"}

        # For confirm/reject/greeting/help/ambiguous — fall through to clarify
        # (confirm/reject are handled before _classify_intent is called in process_turn)
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

    def _handle_agentic_turn(
        self,
        *,
        session_id: int,
        turn_id: int,
        message_text: str,
        context: dict[str, Any],
        planner_decision: ChatPlannerDecision,
        channel_type: str,
        user_id: str | None,
    ) -> dict[str, Any]:
        evidence_bundle: dict[str, Any] = {
            "market_snapshot": [],
            "news_findings": [],
            "sec_findings": [],
            "related_tickers": [],
            "committee_views": [],
            "citations": [],
            "confidence": planner_decision.confidence,
            "next_actions": list(planner_decision.next_actions),
            "warnings": [],
            "resolved_tickers": [],
            "unresolved_subjects": [],
            "comparison_goal": planner_decision.comparison_goal,
            "time_horizon": planner_decision.time_horizon,
            "selection_summary": None,
        }
        context_update = dict(context)

        resolved_tickers: list[str] = []
        resolve_step_id: int | None = None
        resolve_before_cost = self.session_manager.session_cost_total_gbp(session_id)
        if self.settings.conversation_transparency_enabled:
            resolve_step_id = self._begin_workflow_step(
                session_id=session_id,
                turn_id=turn_id,
                step_key="resolving_tickers",
                label="Resolving tickers",
                detail="Mapping company names and references to tradeable symbols.",
                tool_name="resolve_tickers",
            )

        subjects = self._extract_agentic_subjects(message_text, planner_decision, context)
        unresolved_subjects: list[str] = []
        for subject in subjects:
            ticker = resolve_ticker_to_t212(subject)
            if ticker and ticker not in resolved_tickers:
                resolved_tickers.append(ticker)
            elif not ticker and subject not in unresolved_subjects:
                unresolved_subjects.append(subject)
        if (
            not resolved_tickers
            and not subjects
            and self._should_reuse_context_subjects(message_text, planner_decision, context)
        ):
            resolved_tickers = list(context.get("last_subject_tickers") or [])
        evidence_bundle["resolved_tickers"] = list(resolved_tickers)
        evidence_bundle["unresolved_subjects"] = list(unresolved_subjects)
        if self.settings.conversation_transparency_enabled and resolve_step_id is not None:
            self._complete_workflow_step(
                step_id=resolve_step_id,
                session_id=session_id,
                before_cost_gbp=resolve_before_cost,
                detail=(
                    f"Resolved {', '.join(resolved_tickers)}."
                    if resolved_tickers
                    else "No explicit ticker resolved; using portfolio or clarification flow."
                ),
                detail_json={
                    "subjects": subjects,
                    "tickers": resolved_tickers,
                    "unresolved_subjects": unresolved_subjects,
                },
            )

        if planner_decision.route == "compare" and len(resolved_tickers) < 2:
            warning_message = (
                f"I could only resolve {', '.join(resolved_tickers)}. "
                f"I couldn't resolve {', '.join(unresolved_subjects)} from that phrasing."
                if resolved_tickers and unresolved_subjects
                else "I need two ticker symbols or company names to run a comparison."
            )
            evidence_bundle["warnings"].append(
                {
                    "code": "compare_resolution_incomplete",
                    "message": warning_message,
                    "severity": "warning",
                }
            )
            self._emit_chat_warning(
                session_id=session_id,
                turn_id=turn_id,
                message=warning_message,
                detail_json={"subjects": subjects, "tickers": resolved_tickers, "unresolved_subjects": unresolved_subjects},
            )

        if planner_decision.route == "committee_review" and not resolved_tickers:
            warning_message = (
                f"I couldn't resolve {', '.join(unresolved_subjects)} to a tradeable ticker."
                if unresolved_subjects
                else "I need a ticker or company name to generate bull, bear, and risk views."
            )
            evidence_bundle["warnings"].append(
                {
                    "code": "committee_ticker_missing",
                    "message": warning_message,
                    "severity": "warning",
                }
            )
            self._emit_chat_warning(
                session_id=session_id,
                turn_id=turn_id,
                message=warning_message,
                detail_json={"subjects": subjects, "unresolved_subjects": unresolved_subjects},
            )
        compare_incomplete = planner_decision.route == "compare" and len(resolved_tickers) < 2

        if planner_decision.route == "portfolio_analysis":
            evidence_bundle["market_snapshot"] = self._build_portfolio_snapshot()
            context_update["last_selection_tickers"] = resolved_tickers
        elif not compare_incomplete:
            fetch_step_id: int | None = None
            fetch_before_cost = self.session_manager.session_cost_total_gbp(session_id)
            if self.settings.conversation_transparency_enabled and resolved_tickers:
                fetch_step_id = self._begin_workflow_step(
                    session_id=session_id,
                    turn_id=turn_id,
                    step_key="fetching_market_data",
                    label="Fetching market data",
                    detail="Collecting current snapshot, indicators, and fundamentals.",
                    tool_name="get_market_snapshot",
                )
            for ticker in resolved_tickers[:3]:
                snapshot = self._build_market_snapshot_payload(ticker)
                evidence_bundle["market_snapshot"].append(snapshot)
                evidence_bundle["citations"].append(
                    {
                        "id": f"internal-market-{ticker.lower()}",
                        "label": f"{ticker} internal market snapshot",
                        "source_type": "internal_market_data",
                        "provider": "internal",
                        "ticker": ticker,
                    }
                )
            if self.settings.conversation_transparency_enabled and fetch_step_id is not None:
                self._complete_workflow_step(
                    step_id=fetch_step_id,
                    session_id=session_id,
                    before_cost_gbp=fetch_before_cost,
                    detail=f"Fetched structured market data for {', '.join(resolved_tickers[:3])}.",
                    detail_json={"tickers": resolved_tickers[:3]},
                )

        if planner_decision.requires_web_research and resolved_tickers and not compare_incomplete:
            research_step_id: int | None = None
            research_before_cost = self.session_manager.session_cost_total_gbp(session_id)
            if self.settings.conversation_transparency_enabled:
                research_step_id = self._begin_workflow_step(
                    session_id=session_id,
                    turn_id=turn_id,
                    step_key="running_web_research",
                    label="Running web research",
                    detail="Gathering recent external evidence and citations.",
                    tool_name="run_research_search",
                )
            research_executor = ResearchExecutor(cycle_id=f"chat-session-{session_id}-turn-{turn_id}")
            evidence_bundle["news_findings"] = self._run_agentic_research(
                session_id=session_id,
                turn_id=turn_id,
                message_text=message_text,
                tickers=resolved_tickers,
                research_executor=research_executor,
                evidence_bundle=evidence_bundle,
            )
            if self.settings.conversation_transparency_enabled and research_step_id is not None:
                self._complete_workflow_step(
                    step_id=research_step_id,
                    session_id=session_id,
                    before_cost_gbp=research_before_cost,
                    detail="Captured grounded external evidence for the turn.",
                    provider="brave/tavily/sec",
                    tool_name="run_research_search",
                    detail_json={"tickers": resolved_tickers},
                )

        if planner_decision.requires_related_scan and resolved_tickers and not compare_incomplete:
            compare_step_id: int | None = None
            compare_before_cost = self.session_manager.session_cost_total_gbp(session_id)
            if self.settings.conversation_transparency_enabled:
                compare_step_id = self._begin_workflow_step(
                    session_id=session_id,
                    turn_id=turn_id,
                    step_key="comparing_options",
                    label="Comparing nearby options",
                    detail="Scanning related names in the same sector.",
                    tool_name="scan_related_tickers",
                )
            evidence_bundle["related_tickers"] = self._scan_related_tickers(resolved_tickers)
            if self.settings.conversation_transparency_enabled and compare_step_id is not None:
                self._complete_workflow_step(
                    step_id=compare_step_id,
                    session_id=session_id,
                    before_cost_gbp=compare_before_cost,
                    detail="Completed adjacent-name scan for the current thesis.",
                    tool_name="scan_related_tickers",
                    detail_json={"related_tickers": evidence_bundle["related_tickers"]},
                )

        if planner_decision.requires_committee and resolved_tickers:
            committee_step_id: int | None = None
            committee_before_cost = self.session_manager.session_cost_total_gbp(session_id)
            if self.settings.conversation_transparency_enabled:
                committee_step_id = self._begin_workflow_step(
                    session_id=session_id,
                    turn_id=turn_id,
                    step_key="asking_specialist",
                    label="Asking specialists",
                    detail="Generating bull, bear, and risk views from the gathered evidence.",
                )
            evidence_bundle["committee_views"] = self._specialists.build_committee_views(
                tickers=resolved_tickers,
                evidence_bundle=evidence_bundle,
                turn_mode=planner_decision.turn_mode,
            )
            if self.settings.conversation_transparency_enabled and committee_step_id is not None:
                committee_models = [
                    view.get("model")
                    for view in evidence_bundle["committee_views"]
                    if isinstance(view, dict) and view.get("model")
                ]
                self._complete_workflow_step(
                    step_id=committee_step_id,
                    session_id=session_id,
                    before_cost_gbp=committee_before_cost,
                    detail="Specialist perspectives were folded into the final answer.",
                    model=", ".join(committee_models[:3]) if committee_models else None,
                    detail_json={"committee_views": evidence_bundle["committee_views"]},
                )

        winner_summary: dict[str, Any] | None = None
        if planner_decision.route == "compare" and planner_decision.comparison_goal == "pick_strongest":
            winner_summary = self._select_strongest_candidate(
                market_snapshots=evidence_bundle["market_snapshot"],
                time_horizon=planner_decision.time_horizon,
            )
            evidence_bundle["selection_summary"] = winner_summary
            if winner_summary is None:
                warning_message = "I compared the names, but I couldn't pick a single strongest setup confidently from the current evidence."
                evidence_bundle["warnings"].append(
                    {
                        "code": "comparison_winner_uncertain",
                        "message": warning_message,
                        "severity": "warning",
                    }
                )
                self._emit_chat_warning(
                    session_id=session_id,
                    turn_id=turn_id,
                    message=warning_message,
                    detail_json={"tickers": resolved_tickers},
                )

        proactive_result: dict[str, Any] | None = None
        if (
            planner_decision.should_suggest_opportunity
            and self.settings.conversation_proactive_suggestions_enabled
            and not planner_decision.requires_trade_preview
        ):
            proactive_result = self._build_proactive_suggestion(
                session_id=session_id,
                turn_id=turn_id,
                message_text=message_text,
                tickers=resolved_tickers,
                related_tickers=evidence_bundle["related_tickers"],
                channel_type=channel_type,
                user_id=user_id,
            )
            if proactive_result:
                evidence_bundle["next_actions"] = proactive_result.get("next_actions") or evidence_bundle["next_actions"]

        if planner_decision.requires_trade_preview:
            trade_step_id: int | None = None
            trade_before_cost = self.session_manager.session_cost_total_gbp(session_id)
            if self.settings.conversation_transparency_enabled:
                trade_step_id = self._begin_workflow_step(
                    session_id=session_id,
                    turn_id=turn_id,
                    step_key="drafting_trade_preview",
                    label="Drafting trade preview",
                    detail="Building a deterministic preview and safety checks.",
                    tool_name="build_trade_preview",
                )
            intent = self._classify_intent(message_text, context)
            trade_result = self._handle_intent(
                session_id=session_id,
                turn_id=turn_id,
                message_text=message_text,
                intent=intent,
                context=context,
                channel_type=channel_type,
                user_id=user_id,
            )
            result = self._attach_agentic_metadata(
                session_id=session_id,
                turn_id=turn_id,
                result=trade_result,
                planner_decision=planner_decision,
                context=context_update,
                evidence_bundle=evidence_bundle,
            )
            if self.settings.conversation_transparency_enabled and trade_step_id is not None:
                latest_action = (result.get("response_json") or {}).get("status")
                self._complete_workflow_step(
                    step_id=trade_step_id,
                    session_id=session_id,
                    before_cost_gbp=trade_before_cost,
                    detail="Trade preview was created through the deterministic execution path.",
                    tool_name="build_trade_preview",
                    detail_json={"action_status": latest_action},
                )
                if latest_action == "awaiting_confirmation":
                    awaiting = self.session_manager.add_workflow_step(
                        session_id=session_id,
                        turn_id=turn_id,
                        step_key="awaiting_confirmation",
                        status="completed",
                        label="Awaiting confirmation",
                        detail="Preview created. Waiting for operator confirmation before execution.",
                        completed_at=_utcnow(),
                    )
                    self._emit_workflow_event("chat_step_completed", awaiting)
            return result

        build_step_id: int | None = None
        build_before_cost = self.session_manager.session_cost_total_gbp(session_id)
        if self.settings.conversation_transparency_enabled:
            build_step_id = self._begin_workflow_step(
                session_id=session_id,
                turn_id=turn_id,
                step_key="building_answer",
                label="Building answer",
                detail="Composing the final single-assistant response from the evidence bundle.",
                model=self.settings.conversation_planner_model,
            )
        composed = self._planner.compose_response(
            user_message=message_text,
            plan=planner_decision,
            evidence_bundle=evidence_bundle,
        )
        composed_warnings = composed.get("warnings") if isinstance(composed.get("warnings"), list) else []
        for warning in composed_warnings:
            if warning not in evidence_bundle["warnings"]:
                evidence_bundle["warnings"].append(warning)
                self._emit_chat_warning(
                    session_id=session_id,
                    turn_id=turn_id,
                    message=str(warning.get("message") if isinstance(warning, dict) else warning),
                    detail_json=warning if isinstance(warning, dict) else {"message": warning},
                )
        evidence_bundle["confidence"] = composed.get("confidence", evidence_bundle["confidence"])
        evidence_bundle["next_actions"] = composed.get("next_actions") or evidence_bundle["next_actions"]
        assistant_text = composed["assistant_text"]
        if winner_summary is not None:
            selection_prefix = self._render_selection_summary(winner_summary)
            if selection_prefix and selection_prefix not in assistant_text:
                assistant_text = f"{selection_prefix}\n\n{assistant_text}"
        if proactive_result and proactive_result.get("assistant_suffix"):
            assistant_text = f"{assistant_text}\n\n{proactive_result['assistant_suffix']}"

        # Phase 5: Post-composition safety — ensure risk warnings aren't dropped
        assistant_text = apply_safety_check(
            assistant_text,
            evidence_bundle,
            route=planner_decision.route,
        )

        proposed_action: dict[str, Any] | None = None
        if planner_decision.post_compare_trade_intent and winner_summary is not None:
            trade_step_id: int | None = None
            trade_before_cost = self.session_manager.session_cost_total_gbp(session_id)
            if self.settings.conversation_transparency_enabled:
                trade_step_id = self._begin_workflow_step(
                    session_id=session_id,
                    turn_id=turn_id,
                    step_key="drafting_trade_preview",
                    label="Drafting trade preview",
                    detail="Staging a deterministic preview for the strongest compared candidate.",
                    tool_name="build_trade_preview",
                )
            winner_ticker = str(winner_summary["winner_ticker"])
            follow_up_intent = TradeCommandIntent(**planner_decision.post_compare_trade_intent)
            staged_intent = retarget_trade_intent_to_winner(
                follow_up_intent,
                winner_ticker,
                raw_message=message_text,
            )
            trade_result = self._handle_trade_command(
                session_id=session_id,
                turn_id=turn_id,
                intent=staged_intent,
                channel_type=channel_type,
                user_id=user_id,
                context=context_update,
            )
            proposed_action = trade_result.get("response_json") if isinstance(trade_result.get("response_json"), dict) else None
            assistant_text = f"{assistant_text}\n\n{trade_result['assistant_text']}"
            if self.settings.conversation_transparency_enabled and trade_step_id is not None:
                self._complete_workflow_step(
                    step_id=trade_step_id,
                    session_id=session_id,
                    before_cost_gbp=trade_before_cost,
                    detail=f"Preview staged for the strongest compared name: {winner_ticker}.",
                    tool_name="build_trade_preview",
                    detail_json={"winner_ticker": winner_ticker, "action_status": proposed_action.get("status") if proposed_action else None},
                )
                if proposed_action and proposed_action.get("status") == "awaiting_confirmation":
                    awaiting = self.session_manager.add_workflow_step(
                        session_id=session_id,
                        turn_id=turn_id,
                        step_key="awaiting_confirmation",
                        status="completed",
                        label="Awaiting confirmation",
                        detail="Preview created. Waiting for operator confirmation before execution.",
                        completed_at=_utcnow(),
                    )
                    self._emit_workflow_event("chat_step_completed", awaiting)
        if self.settings.conversation_transparency_enabled and build_step_id is not None:
            self._complete_workflow_step(
                step_id=build_step_id,
                session_id=session_id,
                before_cost_gbp=build_before_cost,
                detail="Built the final operator-facing answer with citations and next actions.",
                model=self.settings.conversation_planner_model,
            )
            completed = self.session_manager.add_workflow_step(
                session_id=session_id,
                turn_id=turn_id,
                step_key="completed",
                status="completed",
                label="Completed",
                detail="Agentic turn completed successfully.",
                completed_at=_utcnow(),
            )
            self._emit_workflow_event("chat_step_completed", completed)

        context_update["last_subject_tickers"] = resolved_tickers or context.get("last_subject_tickers") or []
        context_update["last_selection_tickers"] = (
            [row.get("ticker") for row in evidence_bundle["related_tickers"] if row.get("ticker")]
            or resolved_tickers
        )
        return {
            "assistant_text": assistant_text,
            "context_update": context_update,
            "response_json": {
                "kind": "agentic_response",
                "route": planner_decision.route,
                "turn_mode": planner_decision.turn_mode,
                "planner": planner_decision.as_dict(),
                "evidence_blocks": evidence_bundle,
                "citations": evidence_bundle["citations"],
                "related_tickers": evidence_bundle["related_tickers"],
                "committee_views": evidence_bundle["committee_views"],
                "confidence": evidence_bundle["confidence"],
                "next_actions": evidence_bundle["next_actions"],
                "warnings": evidence_bundle["warnings"],
                "selection_summary": evidence_bundle["selection_summary"],
                "proposed_action": proposed_action,
                "proactive_suggestion": proactive_result.get("payload") if proactive_result else None,
            },
        }

    def _attach_agentic_metadata(
        self,
        *,
        session_id: int,
        turn_id: int,
        result: dict[str, Any],
        planner_decision: ChatPlannerDecision,
        context: dict[str, Any],
        evidence_bundle: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bundle = evidence_bundle or {
            "market_snapshot": [],
            "news_findings": [],
            "sec_findings": [],
            "related_tickers": [],
            "committee_views": [],
            "citations": [],
            "confidence": planner_decision.confidence,
            "next_actions": list(planner_decision.next_actions),
            "warnings": [],
            "comparison_goal": planner_decision.comparison_goal,
            "time_horizon": planner_decision.time_horizon,
            "selection_summary": None,
        }
        response_json = result.get("response_json")
        if not isinstance(response_json, dict):
            response_json = {"payload": response_json}
        response_json.update(
            {
                "turn_mode": planner_decision.turn_mode,
                "route": planner_decision.route,
                "planner": planner_decision.as_dict(),
                "evidence_blocks": bundle,
                "citations": bundle.get("citations") or [],
                "related_tickers": bundle.get("related_tickers") or [],
                "committee_views": bundle.get("committee_views") or [],
                "confidence": bundle.get("confidence", planner_decision.confidence),
                "next_actions": bundle.get("next_actions") or planner_decision.next_actions,
                "warnings": bundle.get("warnings") or [],
            }
        )
        result["response_json"] = response_json
        result["context_update"] = result.get("context_update") or context
        return result

    def _handle_help_or_explain(self, message_text: str, context: dict[str, Any]) -> dict[str, Any]:
        del message_text
        return {
            "assistant_text": (
                "I can help with research, comparisons, reviews, bounded trade previews, stop updates, cancellations, "
                "and portfolio rules. Nothing executes directly from chat. If you ask for an action, I will stage a "
                "proposal first and wait for an explicit confirm or reject."
            ),
            "context_update": context,
            "response_json": {"kind": "clarification", "route": "help_or_explain"},
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
        resolved_pairs: list[tuple[str, str]] = []
        unresolved: list[str] = []
        for subject in subjects:
            ticker = resolve_ticker_to_t212(subject)
            if ticker:
                resolved_pairs.append((subject, ticker))
            else:
                unresolved.append(subject)

        tickers = list(dict.fromkeys(ticker for _, ticker in resolved_pairs))
        if not tickers and self._should_reuse_context_subjects(" ".join(subjects), None, context):
            tickers = [ticker for ticker in context["last_subject_tickers"] if ticker]
        if mode == "compare" and len(tickers) < 2:
            unresolved_text = ", ".join(unresolved) if unresolved else "one of those companies"
            if tickers:
                assistant_text = (
                    f"I could only resolve {', '.join(tickers)}. "
                    f"I couldn't resolve {unresolved_text}. "
                    "Use the ticker symbol or a more specific company name and I'll compare them."
                )
            else:
                assistant_text = (
                    f"I couldn't resolve {unresolved_text} to tradeable tickers. "
                    "Use the ticker symbol or a more specific company name and I'll compare them."
                )
            return {
                "assistant_text": assistant_text,
                "context_update": context,
                "response_json": {
                    "kind": "research_error",
                    "resolved_tickers": tickers,
                    "unresolved_subjects": unresolved,
                },
            }
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
        prefix = ""
        if unresolved:
            prefix = (
                "I couldn't resolve these names, so I left them out: "
                + ", ".join(unresolved)
                + ".\n\n"
            )
        return {
            "assistant_text": prefix + f"{header}\n\n" + "\n\n".join(lines),
            "context_update": {
                "last_subject_tickers": tickers,
                "last_selection_tickers": tickers,
            },
            "response_json": {
                "kind": "research",
                "tickers": tickers,
                "unresolved_subjects": unresolved,
            },
        }

    def _extract_agentic_subjects(
        self,
        message_text: str,
        planner_decision: ChatPlannerDecision,
        context: dict[str, Any],
    ) -> list[str]:
        trade_intent = parse_trade_command(message_text, use_llm_fallback=False)
        if trade_intent is not None and trade_intent.subject_phrases:
            return self._resolve_subjects(trade_intent.subject_phrases, context)
        if planner_decision.route == "help_or_explain":
            return []
        if planner_decision.route == "compare":
            if planner_decision.comparison_subjects:
                return self._resolve_subjects(list(planner_decision.comparison_subjects), context)
            compare_request = parse_compare_request(message_text)
            if compare_request is not None:
                return self._resolve_subjects(compare_request.subjects, context)
        if planner_decision.route == "committee_review":
            committee_subjects = self._extract_committee_subject(message_text, context)
            if committee_subjects:
                return committee_subjects
        subjects = self._extract_subjects_for_research(message_text, context)
        if subjects:
            return subjects
        if planner_decision.route == "portfolio_analysis":
            return []
        cleaned = self._normalize_research_subject(message_text)
        return [cleaned] if cleaned and len(cleaned.split()) <= 6 else []

    def _build_market_snapshot_payload(self, ticker_t212: str) -> dict[str, Any]:
        yf_ticker = t212_to_yf(ticker_t212)
        started = time.monotonic()
        analysis = self.data_fetcher.get_stock_analysis_lite(yf_ticker)
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        indicators = analysis.get("indicators") or {}
        fundamentals = analysis.get("fundamentals") or {}

        session = get_session()
        try:
            instrument = session.query(Instrument).filter(Instrument.ticker == ticker_t212).first()
        finally:
            session.close()

        return {
            "ticker": ticker_t212,
            "company_name": instrument.name if instrument else yf_ticker,
            "sector": instrument.sector if instrument else None,
            "industry": instrument.industry if instrument else None,
            "business_summary": (instrument.business_summary or "")[:280] if instrument else "",
            "current_price": _safe_float(indicators.get("current_price")) or _safe_float(analysis.get("current_price")),
            "rsi_14": _safe_float(indicators.get("rsi_14")),
            "relative_strength_6m": _safe_float(analysis.get("relative_strength_6m")),
            "volume_sma_ratio_20": _safe_float(indicators.get("volume_sma_ratio_20")),
            "trailing_pe": _safe_float(fundamentals.get("trailing_pe")),
            "debt_equity": _safe_float(fundamentals.get("debt_equity")),
            "analysis_latency_ms": latency_ms,
        }

    def _run_agentic_research(
        self,
        *,
        session_id: int,
        turn_id: int,
        message_text: str,
        tickers: list[str],
        research_executor: ResearchExecutor,
        evidence_bundle: dict[str, Any],
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        max_calls = max(1, self.settings.conversation_max_research_calls_per_turn)
        calls_used = 0
        for ticker in tickers[:3]:
            if calls_used >= max_calls:
                break
            snapshot = next(
                (row for row in evidence_bundle["market_snapshot"] if row.get("ticker") == ticker),
                None,
            ) or {}
            sector = snapshot.get("sector") or ticker
            query = message_text if len(message_text.split()) <= 14 else f"{ticker} recent catalysts and risks"
            search_started = time.monotonic()
            results = research_executor.news_search("strategy", ticker, query, num_results=3)
            latency_ms = round((time.monotonic() - search_started) * 1000, 2)
            calls_used += 1
            summary = ", ".join(item.get("title") or "Untitled result" for item in results[:2]) or query
            self.session_manager.add_research_log(
                session_id=session_id,
                turn_id=turn_id,
                tool_name="run_research_search",
                provider="brave",
                query=query,
                result_summary=summary[:500],
                latency_ms=latency_ms,
            )
            for idx, item in enumerate(results[:3], start=1):
                finding = {
                    "ticker": ticker,
                    "title": item.get("title"),
                    "summary": item.get("snippet"),
                    "url": item.get("url"),
                    "provider": "brave",
                    "tool_name": "news_search",
                }
                findings.append(finding)
                evidence_bundle["citations"].append(
                    {
                        "id": f"search-{ticker.lower()}-{idx}",
                        "label": item.get("title") or f"{ticker} result {idx}",
                        "url": item.get("url"),
                        "source_type": "web_search",
                        "provider": "brave",
                        "ticker": ticker,
                    }
                )
            if calls_used >= max_calls:
                break
            sec_results = research_executor.sec_search_tool("strategy", ticker, doc_type="10-K", num_results=1)
            if sec_results:
                calls_used += 1
                sec_item = sec_results[0]
                sec_summary = f"{sec_item.get('filing_type')} filed {sec_item.get('filing_date')}"
                evidence_bundle["sec_findings"].append(
                    {
                        "ticker": ticker,
                        "title": sec_item.get("description") or sec_summary,
                        "summary": sec_summary,
                        "url": sec_item.get("url"),
                        "provider": "sec",
                    }
                )
                evidence_bundle["citations"].append(
                    {
                        "id": f"sec-{ticker.lower()}",
                        "label": sec_item.get("description") or sec_summary,
                        "url": sec_item.get("url"),
                        "source_type": "sec_filing",
                        "provider": "sec",
                        "ticker": ticker,
                    }
                )
                self.session_manager.add_research_log(
                    session_id=session_id,
                    turn_id=turn_id,
                    tool_name="run_sec_research",
                    provider="sec",
                    query=f"{ticker} 10-K",
                    result_summary=sec_summary[:500],
                )
            if sector and calls_used < max_calls and len(tickers) == 1 and ("related" in message_text.lower() or "space" in message_text.lower()):
                peer_query = f"{sector} leaders relative strength"
                peer_results = research_executor.sector_search("strategy", ticker, str(sector), peer_query, num_results=2)
                calls_used += 1
                for idx, item in enumerate(peer_results[:2], start=1):
                    findings.append(
                        {
                            "ticker": ticker,
                            "title": item.get("title"),
                            "summary": item.get("snippet"),
                            "url": item.get("url"),
                            "provider": "brave",
                            "tool_name": "sector_search",
                        }
                    )
                    evidence_bundle["citations"].append(
                        {
                            "id": f"sector-{ticker.lower()}-{idx}",
                            "label": item.get("title") or f"{ticker} sector result {idx}",
                            "url": item.get("url"),
                            "source_type": "sector_search",
                            "provider": "brave",
                            "ticker": ticker,
                        }
                    )
        return findings

    def _scan_related_tickers(self, base_tickers: list[str]) -> list[dict[str, Any]]:
        if not base_tickers:
            return []
        session = get_session()
        try:
            base = session.query(Instrument).filter(Instrument.ticker == base_tickers[0]).first()
            if base is None:
                return []
            peer_query = session.query(Instrument).filter(
                Instrument.ticker != base.ticker,
                Instrument.data_available.isnot(False),
            )
            if base.industry:
                peer_query = peer_query.filter(Instrument.industry == base.industry)
            elif base.sector:
                peer_query = peer_query.filter(Instrument.sector == base.sector)
            peers = peer_query.order_by(Instrument.market_cap.desc().nullslast(), Instrument.ticker.asc()).limit(16).all()
        finally:
            session.close()

        base_suffix = "_".join(str(base.ticker).split("_")[1:]) if "_" in str(base.ticker) else ""
        base_market_cap = float(base.market_cap or 0) if getattr(base, "market_cap", None) else 0.0
        ranked: list[dict[str, Any]] = []
        for peer in peers:
            peer_suffix = "_".join(str(peer.ticker).split("_")[1:]) if "_" in str(peer.ticker) else ""
            if base_suffix and peer_suffix and peer_suffix != base_suffix:
                continue
            if base_market_cap and peer.market_cap:
                ratio = float(peer.market_cap) / base_market_cap if base_market_cap else 1.0
                if ratio < 0.2 or ratio > 10.0:
                    continue
            snapshot = self._build_market_snapshot_payload(str(peer.ticker))
            similarity_bonus = 0.6 if peer.industry and peer.industry == base.industry else 0.25
            score = (
                similarity_bonus
                + float(snapshot.get("relative_strength_6m") or 0.0)
                - max(0.0, (float(snapshot.get("rsi_14") or 50.0) - 70.0) / 100.0)
                - max(0.0, (float(snapshot.get("debt_equity") or 0.0) - 2.0) / 10.0)
            )
            ranked.append(
                {
                    "ticker": peer.ticker,
                    "label": peer.name or peer.ticker,
                    "sector": peer.sector,
                    "industry": peer.industry,
                    "score": round(score, 3),
                    "current_price": snapshot.get("current_price"),
                    "relative_strength_6m": snapshot.get("relative_strength_6m"),
                    "rsi_14": snapshot.get("rsi_14"),
                    "similarity": "industry" if peer.industry and peer.industry == base.industry else "sector",
                }
            )
        ranked.sort(key=lambda row: row["score"], reverse=True)
        return ranked[:3]

    def _build_portfolio_snapshot(self) -> list[dict[str, Any]]:
        positions = self._get_portfolio_positions()
        return [
            {
                "ticker": pos["ticker"],
                "value_gbp": pos["value_gbp"],
                "pnl_pct": pos["pnl_pct"],
                "quantity": pos["quantity"],
                "current_price": pos["current_price"],
            }
            for pos in positions[:8]
        ]

    def _build_proactive_suggestion(
        self,
        *,
        session_id: int,
        turn_id: int,
        message_text: str,
        tickers: list[str],
        related_tickers: list[dict[str, Any]],
        channel_type: str,
        user_id: str | None,
    ) -> dict[str, Any] | None:
        lowered = message_text.lower()
        if "buy" not in lowered and "interesting" not in lowered and "opportunit" not in lowered and "stronger" not in lowered:
            return None
        candidate = related_tickers[0]["ticker"] if related_tickers else (tickers[0] if tickers else None)
        if not candidate:
            return None
        try:
            intent = TradeCommandIntent(
                action="BUY",
                ticker=candidate,
                raw_message=f"BUY {candidate}",
                command_kind="trade",
                execution_mode="strategy",
                subject_phrases=[candidate],
            )
            result = self._handle_trade_command(
                session_id=session_id,
                turn_id=turn_id,
                intent=intent,
                channel_type=channel_type,
                user_id=user_id,
                context={"last_subject_tickers": tickers},
            )
            response_json = result.get("response_json") if isinstance(result.get("response_json"), dict) else {}
            if response_json.get("status") != "awaiting_confirmation":
                return None
            suffix = (
                f"Opportunity suggestion: based on the current evidence, {candidate} looks like the strongest adjacent setup. "
                "I staged a preview so you can confirm or reject it explicitly."
            )
            return {
                "assistant_suffix": suffix,
                "payload": response_json,
                "next_actions": ["confirm", "reject", "show committee views"],
            }
        except Exception:
            logger.warning("Failed to build proactive suggestion preview", exc_info=True)
            return None

    def _begin_workflow_step(
        self,
        *,
        session_id: int,
        turn_id: int,
        step_key: str,
        label: str,
        detail: str,
        provider: str | None = None,
        model: str | None = None,
        tool_name: str | None = None,
        detail_json: Any | None = None,
    ) -> int:
        step = self.session_manager.add_workflow_step(
            session_id=session_id,
            turn_id=turn_id,
            step_key=step_key,
            status="running",
            label=label,
            detail=detail,
            provider=provider,
            model=model,
            tool_name=tool_name,
            detail_json=detail_json,
        )
        self._emit_workflow_event("chat_step_started", step)
        return int(step["id"])

    def _complete_workflow_step(
        self,
        *,
        step_id: int,
        session_id: int,
        before_cost_gbp: float,
        detail: str,
        provider: str | None = None,
        model: str | None = None,
        tool_name: str | None = None,
        detail_json: Any | None = None,
    ) -> dict[str, Any]:
        step = self.session_manager.update_workflow_step(
            step_id,
            status="completed",
            detail=detail,
            provider=provider,
            model=model,
            tool_name=tool_name,
            cost_gbp=self._cost_delta_for_step(session_id, before_cost_gbp),
            completed_at=_utcnow(),
            detail_json=detail_json,
        )
        self._emit_workflow_event("chat_step_completed", step)
        return step

    def _cost_delta_for_step(self, session_id: int, before_cost_gbp: float) -> float:
        after_cost = self.session_manager.session_cost_total_gbp(session_id)
        return round(max(0.0, after_cost - before_cost_gbp), 4)

    def _emit_workflow_event(self, event_type: str, step: dict[str, Any]) -> None:
        self._emit_event(
            event_type,
            step.get("detail") or step.get("label") or step.get("step_key") or "Workflow step updated",
            session_id=step.get("session_id"),
            turn_id=step.get("turn_id"),
            step_id=step.get("id"),
            step_key=step.get("step_key"),
            status=step.get("status"),
            provider=step.get("provider"),
            model=step.get("model"),
            tool_name=step.get("tool_name"),
            cost_gbp=step.get("cost_gbp"),
            latency_ms=step.get("latency_ms"),
        )

    def _emit_chat_warning(
        self,
        *,
        session_id: int,
        turn_id: int,
        message: str,
        detail_json: Any | None = None,
    ) -> None:
        self._emit_event(
            "chat_warning",
            message,
            session_id=session_id,
            turn_id=turn_id,
            detail_json=detail_json,
        )

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
        self._mirror_assistant_reply_to_slack(
            session_id=session_id,
            message_text=message_text,
            source_channel_type=channel_type,
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
            if order_class != "any" and classified != order_class:
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
            order_label = "order" if order_class == "any" else order_class.replace("_", " ")
            preview_lines = [f"Matched {len(matches)} pending {order_label}(s):"]
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
        compare_request = parse_compare_request(message_text)
        if compare_request is not None:
            return self._resolve_subjects(compare_request.subjects, context)
        if any(
            token in lowered
            for token in (
                "what about",
                "dig deeper",
                "explain",
                "research",
                "look into",
                "compare",
                "happening with",
                "views on",
                "pros and cons",
                "bull and bear",
                "committee view",
            )
        ):
            chunks = re.split(r"\band\b|,|vs\.?|versus", message_text, flags=re.IGNORECASE)
            subjects = [self._normalize_research_subject(chunk) for chunk in chunks]
            subjects = [self._resolve_subject(subject, context) for subject in subjects]
            subjects = [subject for subject in subjects if subject and len(subject.split()) <= 6]
            if subjects:
                return subjects
            if self._should_reuse_context_subjects(message_text, None, context):
                return list(context["last_subject_tickers"])
        return []

    def _normalize_research_subject(self, subject: str) -> str:
        cleaned = _clean_text(subject).strip(".,?!:;")
        cleaned = RESEARCH_PREFIX_RE.sub("", cleaned).strip(".,?!:;")
        target_match = TARGET_SUFFIX_RE.search(cleaned)
        if target_match:
            cleaned = _clean_text(target_match.group("subject")).strip(".,?!:;")
        return cleaned

    def _extract_committee_subject(self, message_text: str, context: dict[str, Any]) -> list[str]:
        match = COMMITTEE_SUBJECT_RE.search(message_text)
        if match:
            subject = self._normalize_research_subject(match.group("subject"))
            resolved = self._resolve_subject(subject, context)
            return [resolved] if resolved else []
        fallback = self._normalize_research_subject(message_text)
        if fallback and len(fallback.split()) <= 3:
            resolved = self._resolve_subject(fallback, context)
            return [resolved] if resolved else []
        return []

    def _should_reuse_context_subjects(
        self,
        message_text: str,
        planner_decision: ChatPlannerDecision | None,
        context: dict[str, Any],
    ) -> bool:
        if not context.get("last_subject_tickers"):
            return False
        if planner_decision and planner_decision.route in {"help_or_explain", "portfolio_analysis", "compare"}:
            return False
        if parse_trade_command(message_text, use_llm_fallback=False) is not None:
            return False
        return FOLLOW_UP_CONTEXT_RE.search(message_text) is not None

    def _select_strongest_candidate(
        self,
        *,
        market_snapshots: list[dict[str, Any]],
        time_horizon: str | None,
    ) -> dict[str, Any] | None:
        if len(market_snapshots) < 2:
            return None

        ranked: list[dict[str, Any]] = []
        for snapshot in market_snapshots:
            ticker = snapshot.get("ticker")
            if not ticker:
                continue
            relative_strength = float(snapshot.get("relative_strength_6m") or 0.0)
            rsi = float(snapshot.get("rsi_14") or 50.0)
            debt_equity = float(snapshot.get("debt_equity") or 0.0)
            trailing_pe = float(snapshot.get("trailing_pe") or 0.0)
            score = (
                relative_strength
                - abs(rsi - 55.0) / 100.0
                - max(0.0, debt_equity - 2.0) / 10.0
                - max(0.0, trailing_pe - 40.0) / 150.0
            )
            ranked.append(
                {
                    "ticker": ticker,
                    "company_name": snapshot.get("company_name") or ticker,
                    "score": round(score, 4),
                    "relative_strength_6m": round(relative_strength, 4),
                    "rsi_14": round(rsi, 2),
                }
            )

        if len(ranked) < 2:
            return None

        ranked.sort(key=lambda item: item["score"], reverse=True)
        winner = ranked[0]
        runner_up = ranked[1]
        if winner["score"] - runner_up["score"] < 0.08:
            return None

        reason = (
            f"higher relative strength ({winner['relative_strength_6m']:.2f}) "
            f"and steadier momentum than {runner_up['ticker']}"
        )
        return {
            "winner_ticker": winner["ticker"],
            "winner_company_name": winner["company_name"],
            "reason": reason,
            "time_horizon": time_horizon,
            "scores": ranked,
        }

    def _render_selection_summary(self, selection_summary: dict[str, Any] | None) -> str:
        if not selection_summary or not selection_summary.get("winner_ticker"):
            return ""
        ticker = str(selection_summary["winner_ticker"])
        reason = selection_summary.get("reason")
        horizon = selection_summary.get("time_horizon")
        sentence = f"Strongest setup: {ticker}"
        if horizon:
            sentence += f" over the next {horizon}"
        if reason:
            sentence += f", driven by {reason}"
        return sentence + "."

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

    def _get_slack_web_client(self) -> Any | None:
        if self._slack_web_client is not None:
            return self._slack_web_client

        bot_token = self.settings.slack_bot_token
        if not bot_token:
            return None

        try:
            from slack_sdk import WebClient
        except Exception:
            logger.debug("slack_sdk unavailable; skipping Slack mirror", exc_info=True)
            return None

        self._slack_web_client = WebClient(token=bot_token)
        return self._slack_web_client

    def _chunk_slack_reply(self, text: str, *, max_chars: int = SLACK_REPLY_MAX_CHARS) -> list[str]:
        if len(text) <= max_chars:
            return [text]

        lines = text.splitlines()
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for line in lines:
            line_len = len(line) + 1
            if current and current_len + line_len > max_chars:
                chunks.append("\n".join(current))
                current = [line]
                current_len = line_len
            else:
                current.append(line)
                current_len += line_len

        if current:
            chunks.append("\n".join(current))
        return chunks or [text]

    def _mirror_assistant_reply_to_slack(
        self,
        *,
        session_id: int,
        message_text: str,
        source_channel_type: str,
    ) -> None:
        if source_channel_type == "slack" or not message_text.strip():
            return

        session_detail = self.session_manager.get_session(session_id)
        if not session_detail or session_detail.get("channel_type") != "slack":
            return

        thread_ts = str(session_detail.get("channel_session_key") or "").strip()
        channel_id = str(self.settings.slack_trade_channel_id or "").strip()
        if not thread_ts or not channel_id:
            return

        client = self._get_slack_web_client()
        if client is None:
            return

        try:
            for idx, chunk in enumerate(self._chunk_slack_reply(message_text)):
                chunk_text = chunk if idx == 0 else f"(continued)\n{chunk}"
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=chunk_text,
                )
        except Exception:
            logger.warning(
                "Failed to mirror dashboard reply to Slack thread for session %s",
                session_id,
                exc_info=True,
            )
