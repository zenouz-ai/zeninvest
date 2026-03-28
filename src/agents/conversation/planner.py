"""Planner and composer for agentic conversational trading."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from typing import Any

import openai

from src.agents.conversation.compare_parser import parse_compare_request
from src.agents.notifications.trade_command_parser import parse_trade_command
from src.utils.config import get_settings
from src.utils.cost_tracker import Provider, check_budget, log_cost
from src.utils.logger import get_logger

logger = get_logger("conversation_planner")

COMPARE_HINT_RE = re.compile(r"\b(compare|contrast|versus|vs\.?)\b", re.IGNORECASE)
COMMITTEE_HINT_RE = re.compile(r"\b(bull|bear|risk|committee|debate|pros and cons)\b", re.IGNORECASE)
PORTFOLIO_HINT_RE = re.compile(r"\b(portfolio|holdings|exposure|allocation|positions)\b", re.IGNORECASE)
OPPORTUNITY_HINT_RE = re.compile(r"\b(interesting|ideas|opportunities|what should i buy|stronger one|best in this space)\b", re.IGNORECASE)
RESEARCH_HINT_RE = re.compile(r"\b(compare|research|analyze|analysis|what about|how about|tell me about|look into|dig deeper|explain)\b", re.IGNORECASE)
GREETING_HINT_RE = re.compile(r"^\s*(hi|hello|hey|thanks|thank you)\b", re.IGNORECASE)
HELP_HINT_RE = re.compile(
    r"\b(help|how does this work|how this works|understand this workflow|what can you do|what does this do)\b",
    re.IGNORECASE,
)
PEER_SCAN_HINT_RE = re.compile(
    r"\b(related|peer|peers|adjacent|stronger|best in this space|what else|other names|nearby names)\b",
    re.IGNORECASE,
)


@dataclass
class ChatPlannerDecision:
    """Structured plan emitted by the planner."""

    route: str
    turn_mode: str
    use_fast_path: bool
    requires_web_research: bool
    requires_related_scan: bool
    requires_committee: bool
    requires_trade_preview: bool
    should_suggest_opportunity: bool
    confidence: float
    next_actions: list[str]
    explanation: str
    comparison_goal: str | None = None
    comparison_subjects: list[str] | None = None
    time_horizon: str | None = None
    post_compare_trade_intent: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "turn_mode": self.turn_mode,
            "use_fast_path": self.use_fast_path,
            "requires_web_research": self.requires_web_research,
            "requires_related_scan": self.requires_related_scan,
            "requires_committee": self.requires_committee,
            "requires_trade_preview": self.requires_trade_preview,
            "should_suggest_opportunity": self.should_suggest_opportunity,
            "confidence": self.confidence,
            "next_actions": list(self.next_actions),
            "explanation": self.explanation,
            "comparison_goal": self.comparison_goal,
            "comparison_subjects": list(self.comparison_subjects or []),
            "time_horizon": self.time_horizon,
            "post_compare_trade_intent": self.post_compare_trade_intent,
        }


class ChatPlanner:
    """Lightweight planner with optional OpenAI escalation for substantive turns."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def plan_turn(
        self,
        *,
        message_text: str,
        context: dict[str, Any],
        requested_mode: str | None = None,
        budget_tier: str | None = None,
    ) -> ChatPlannerDecision:
        heuristic = self._heuristic_plan(
            message_text=message_text,
            context=context,
            requested_mode=requested_mode,
        )
        if requested_mode == "quick" and not heuristic.requires_trade_preview:
            heuristic = replace(
                heuristic,
                turn_mode="quick",
                use_fast_path=True,
                requires_web_research=False,
                requires_related_scan=False,
                requires_committee=False,
                should_suggest_opportunity=False,
                explanation="Operator selected quick mode; using the deterministic fast path.",
            )
        if os.getenv("INVESTMENT_AGENT_USE_INMEMORY_DB") == "1":
            return ChatPlannerDecision(
                route=heuristic.route,
                turn_mode=heuristic.turn_mode,
                use_fast_path=True,
                requires_web_research=False,
                requires_related_scan=False,
                requires_committee=False,
                requires_trade_preview=heuristic.requires_trade_preview,
                should_suggest_opportunity=False,
                confidence=heuristic.confidence,
                next_actions=heuristic.next_actions,
                explanation=f"{heuristic.explanation} Test mode used deterministic fallback.",
            )
        if (
            not self.settings.conversation_agentic_planner_enabled
            or heuristic.use_fast_path
        ):
            return heuristic

        if not self.settings.openai_api_key_optional:
            return self._annotate_planner_fallback(
                heuristic,
                "Planner unavailable, using safe fallback because the OpenAI key is missing.",
            )
        if not check_budget(Provider.OPENAI.value):
            return self._annotate_planner_fallback(
                heuristic,
                "Planner unavailable, using safe fallback because the OpenAI budget is exhausted.",
            )

        try:
            decision = self._plan_with_openai(
                message_text=message_text,
                context=context,
                requested_mode=requested_mode,
                budget_tier=budget_tier,
                heuristic=heuristic,
            )
            return decision
        except Exception as exc:
            logger.warning("Planner fell back to heuristic routing: %s", exc, exc_info=True)
            return self._annotate_planner_fallback(
                heuristic,
                "Planner unavailable, using safe fallback for this turn.",
            )

    def compose_response(
        self,
        *,
        user_message: str,
        plan: ChatPlannerDecision,
        evidence_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        fallback = self._compose_fallback(plan=plan, evidence_bundle=evidence_bundle)
        if os.getenv("INVESTMENT_AGENT_USE_INMEMORY_DB") == "1":
            return fallback
        if not self.settings.conversation_agentic_planner_enabled:
            return fallback
        if not self.settings.openai_api_key_optional:
            return self._append_warning(
                fallback,
                "composer_unavailable",
                "Composer unavailable, using a deterministic fallback because the OpenAI key is missing.",
            )
        if not check_budget(Provider.OPENAI.value):
            return self._append_warning(
                fallback,
                "composer_unavailable",
                "Composer unavailable, using a deterministic fallback because the OpenAI budget is exhausted.",
            )

        try:
            parsed = self._openai_json_response(
                purpose="conversation_composer",
                cycle_id=f"chat-compose-{plan.route}",
                instructions=(
                    "You are the single operator-facing assistant for an investment system. "
                    "Write concise, source-aware replies. Never reveal hidden reasoning. "
                    "If evidence is incomplete, say so. Respond with JSON only."
                ),
                payload={
                    "user_message": user_message,
                    "route": plan.route,
                    "turn_mode": plan.turn_mode,
                    "evidence_bundle": evidence_bundle,
                },
                max_output_tokens=1400,
                temperature=0.35,
            )
            assistant_text = str(parsed.get("assistant_text") or "").strip()
            next_actions = parsed.get("next_actions")
            if not assistant_text:
                return fallback
            return {
                "assistant_text": assistant_text,
                "confidence": parsed.get("confidence", evidence_bundle.get("confidence")),
                "next_actions": next_actions if isinstance(next_actions, list) else fallback["next_actions"],
                "warnings": parsed.get("warnings") if isinstance(parsed.get("warnings"), list) else fallback["warnings"],
            }
        except Exception as exc:
            logger.warning("Composer fell back to deterministic rendering: %s", exc, exc_info=True)
            return self._append_warning(
                fallback,
                "composer_unavailable",
                "Composer unavailable, using a deterministic fallback for this turn.",
            )

    def _heuristic_plan(
        self,
        *,
        message_text: str,
        context: dict[str, Any],
        requested_mode: str | None,
    ) -> ChatPlannerDecision:
        normalized = (message_text or "").strip()
        lowered = normalized.lower()
        trade_intent = parse_trade_command(normalized, use_llm_fallback=False)

        if requested_mode == "committee" and not HELP_HINT_RE.search(normalized) and not COMPARE_HINT_RE.search(normalized):
            return ChatPlannerDecision(
                route="committee_review",
                turn_mode="committee",
                use_fast_path=False,
                requires_web_research=True,
                requires_related_scan=PEER_SCAN_HINT_RE.search(normalized) is not None,
                requires_committee=True,
                requires_trade_preview=False,
                should_suggest_opportunity=False,
                confidence=0.72,
                next_actions=["preview trade", "show related tickers", "explain why not"],
                explanation="Operator explicitly requested committee mode.",
            )
        if requested_mode == "trade" and trade_intent is not None:
            return ChatPlannerDecision(
                route="trade_preview",
                turn_mode="trade",
                use_fast_path=False,
                requires_web_research=True,
                requires_related_scan=False,
                requires_committee=True,
                requires_trade_preview=True,
                should_suggest_opportunity=False,
                confidence=0.84,
                next_actions=["confirm", "reject", "show bull bear risk"],
                explanation="Operator explicitly requested trade mode for a direct trade command.",
            )
        if trade_intent is not None:
            return ChatPlannerDecision(
                route="trade_preview",
                turn_mode="trade",
                use_fast_path=True,
                requires_web_research=False,
                requires_related_scan=False,
                requires_committee=False,
                requires_trade_preview=True,
                should_suggest_opportunity=False,
                confidence=0.95,
                next_actions=["confirm", "reject"],
                explanation="Deterministic trade parser matched the request.",
            )
        if GREETING_HINT_RE.search(normalized):
            return ChatPlannerDecision(
                route="quick_answer",
                turn_mode=requested_mode or "quick",
                use_fast_path=True,
                requires_web_research=False,
                requires_related_scan=False,
                requires_committee=False,
                requires_trade_preview=False,
                should_suggest_opportunity=False,
                confidence=0.99,
                next_actions=["compare two tickers", "review a ticker", "preview a trade"],
                explanation="Greeting or low-risk conversational turn.",
                comparison_subjects=[],
            )
        if HELP_HINT_RE.search(normalized):
            return ChatPlannerDecision(
                route="help_or_explain",
                turn_mode="quick",
                use_fast_path=True,
                requires_web_research=False,
                requires_related_scan=False,
                requires_committee=False,
                requires_trade_preview=False,
                should_suggest_opportunity=False,
                confidence=0.94,
                next_actions=["compare two tickers", "review a ticker", "preview a trade"],
                explanation="Operator asked for workflow help or system guidance.",
                comparison_subjects=[],
            )
        if COMPARE_HINT_RE.search(normalized):
            compare_request = parse_compare_request(normalized)
            requires_related_scan = bool(re.search(r"\b(related|peer|peers|adjacent|what else|other names|nearby names)\b", normalized, re.IGNORECASE))
            return ChatPlannerDecision(
                route="compare",
                turn_mode="committee" if requested_mode == "committee" else (requested_mode or "research"),
                use_fast_path=False,
                requires_web_research=True,
                requires_related_scan=requires_related_scan,
                requires_committee=requested_mode == "committee",
                requires_trade_preview=False,
                should_suggest_opportunity=False,
                confidence=0.78,
                next_actions=["show sources", "compare peers", "preview trade"],
                explanation="Operator asked for a side-by-side comparison.",
                comparison_goal=compare_request.comparison_goal if compare_request else "compare",
                comparison_subjects=list(compare_request.subjects) if compare_request else [],
                time_horizon=compare_request.time_horizon if compare_request else None,
                post_compare_trade_intent=(
                    compare_request.as_dict().get("post_compare_trade_intent")
                    if compare_request and compare_request.post_compare_trade_intent is not None
                    else None
                ),
            )
        if PORTFOLIO_HINT_RE.search(normalized):
            return ChatPlannerDecision(
                route="portfolio_analysis",
                turn_mode=requested_mode or "research",
                use_fast_path=False,
                requires_web_research=False,
                requires_related_scan=False,
                requires_committee="risk" in lowered or "committee" in lowered,
                requires_trade_preview=False,
                should_suggest_opportunity="what should i buy" in lowered,
                confidence=0.7,
                next_actions=["show exposures", "show opportunities", "preview a rebalance"],
                explanation="Portfolio-specific question.",
                comparison_subjects=[],
            )
        if OPPORTUNITY_HINT_RE.search(normalized):
            return ChatPlannerDecision(
                route="opportunity_suggestion",
                turn_mode=requested_mode or "research",
                use_fast_path=False,
                requires_web_research=True,
                requires_related_scan=True,
                requires_committee=True,
                requires_trade_preview=False,
                should_suggest_opportunity=True,
                confidence=0.76,
                next_actions=["show strongest related ticker", "preview trade", "show committee views"],
                explanation="Open-ended opportunity request.",
                comparison_subjects=[],
            )
        if COMMITTEE_HINT_RE.search(normalized):
            return ChatPlannerDecision(
                route="committee_review",
                turn_mode=requested_mode or "committee",
                use_fast_path=False,
                requires_web_research=True,
                requires_related_scan=PEER_SCAN_HINT_RE.search(normalized) is not None,
                requires_committee=True,
                requires_trade_preview=False,
                should_suggest_opportunity=False,
                confidence=0.74,
                next_actions=["preview trade", "show related tickers", "compare peers"],
                explanation="User asked for explicit analyst-style viewpoints.",
                comparison_subjects=[],
            )
        if requested_mode == "trade":
            return ChatPlannerDecision(
                route="trade_preview",
                turn_mode="trade",
                use_fast_path=False,
                requires_web_research=True,
                requires_related_scan=False,
                requires_committee=True,
                requires_trade_preview=True,
                should_suggest_opportunity=False,
                confidence=0.68,
                next_actions=["preview trade", "show committee views", "explain risk"],
                explanation="Operator requested trade mode.",
                comparison_subjects=[],
            )
        if RESEARCH_HINT_RE.search(normalized) or context.get("last_subject_tickers"):
            route = "related_ticker_scan" if PEER_SCAN_HINT_RE.search(normalized) is not None else "grounded_research"
            return ChatPlannerDecision(
                route=route,
                turn_mode=requested_mode or "research",
                use_fast_path=False,
                requires_web_research=True,
                requires_related_scan=route == "related_ticker_scan",
                requires_committee=requested_mode == "committee",
                requires_trade_preview=False,
                should_suggest_opportunity=route == "related_ticker_scan" and "stronger" in lowered,
                confidence=0.71,
                next_actions=["compare peers", "show sources", "preview trade"],
                explanation="Substantive research-style question.",
                comparison_subjects=[],
            )
        return ChatPlannerDecision(
            route="quick_answer",
            turn_mode=requested_mode or "research",
            use_fast_path=False,
            requires_web_research=False,
            requires_related_scan=False,
            requires_committee=False,
            requires_trade_preview=False,
            should_suggest_opportunity=False,
            confidence=0.55,
            next_actions=["compare tickers", "review a ticker", "ask for opportunities"],
            explanation="Defaulted to lightweight agentic clarification mode.",
            comparison_subjects=[],
        )

    def _plan_with_openai(
        self,
        *,
        message_text: str,
        context: dict[str, Any],
        requested_mode: str | None,
        budget_tier: str | None,
        heuristic: ChatPlannerDecision,
    ) -> ChatPlannerDecision:
        payload = self._openai_json_response(
            purpose="conversation_planner",
            cycle_id="chat-plan",
            instructions=(
                "You are the route planner for an audited investment-operations chat. "
                "Choose the minimum route that still answers the request well. "
                "Never permit direct trade execution. Respond with JSON only."
            ),
            payload={
                "message_text": message_text,
                "requested_mode": requested_mode,
                "budget_tier": budget_tier,
                "context": {
                    "last_subject_tickers": context.get("last_subject_tickers") or [],
                    "last_selection_tickers": context.get("last_selection_tickers") or [],
                },
                "heuristic_default": heuristic.as_dict(),
                "allowed_routes": [
                    "help_or_explain",
                    "quick_answer",
                    "compare",
                    "grounded_research",
                    "related_ticker_scan",
                    "committee_review",
                    "portfolio_analysis",
                    "trade_preview",
                    "opportunity_suggestion",
                ],
            },
            max_output_tokens=900,
            temperature=0.2,
        )
        route = str(payload.get("route") or heuristic.route)
        turn_mode = str(payload.get("turn_mode") or requested_mode or heuristic.turn_mode)
        next_actions = payload.get("next_actions")
        allowed_routes = {
            "help_or_explain",
            "quick_answer",
            "compare",
            "grounded_research",
            "related_ticker_scan",
            "committee_review",
            "portfolio_analysis",
            "trade_preview",
            "opportunity_suggestion",
        }
        return ChatPlannerDecision(
            route=route if route in allowed_routes else heuristic.route,
            turn_mode=turn_mode if turn_mode in {"quick", "research", "committee", "trade"} else heuristic.turn_mode,
            use_fast_path=bool(payload.get("use_fast_path", heuristic.use_fast_path)),
            requires_web_research=bool(payload.get("requires_web_research", heuristic.requires_web_research)),
            requires_related_scan=bool(payload.get("requires_related_scan", heuristic.requires_related_scan)),
            requires_committee=bool(payload.get("requires_committee", heuristic.requires_committee)),
            requires_trade_preview=bool(payload.get("requires_trade_preview", heuristic.requires_trade_preview)),
            should_suggest_opportunity=bool(
                payload.get("should_suggest_opportunity", heuristic.should_suggest_opportunity)
            ),
            confidence=float(payload.get("confidence", heuristic.confidence) or heuristic.confidence),
            next_actions=next_actions if isinstance(next_actions, list) and next_actions else heuristic.next_actions,
            explanation=str(payload.get("explanation") or heuristic.explanation),
            comparison_goal=str(payload.get("comparison_goal") or heuristic.comparison_goal or "").strip() or None,
            comparison_subjects=(
                payload.get("comparison_subjects")
                if isinstance(payload.get("comparison_subjects"), list)
                else list(heuristic.comparison_subjects or [])
            ),
            time_horizon=str(payload.get("time_horizon") or heuristic.time_horizon or "") or None,
            post_compare_trade_intent=(
                payload.get("post_compare_trade_intent")
                if isinstance(payload.get("post_compare_trade_intent"), dict)
                else heuristic.post_compare_trade_intent
            ),
        )

    def _compose_fallback(self, *, plan: ChatPlannerDecision, evidence_bundle: dict[str, Any]) -> dict[str, Any]:
        market_snapshots = evidence_bundle.get("market_snapshot") or []
        research = evidence_bundle.get("news_findings") or []
        related = evidence_bundle.get("related_tickers") or []
        committee = evidence_bundle.get("committee_views") or []
        warnings = list(evidence_bundle.get("warnings") or [])
        resolved_tickers = list(evidence_bundle.get("resolved_tickers") or [])
        unresolved_subjects = list(evidence_bundle.get("unresolved_subjects") or [])
        lines = []
        selection_summary = evidence_bundle.get("selection_summary") or {}

        if plan.route == "help_or_explain":
            lines.extend(
                [
                    "I can help with research, comparisons, reviews, bounded trade previews, stop updates, cancellations, and simple portfolio rules.",
                    "Nothing executes directly from chat. If you ask for execution, I will stage a proposal first and wait for an explicit confirm or reject.",
                    "You can start with prompts like `compare tesla and google`, `give me bull and bear views on AMD`, or `buy £25 AMD`.",
                ]
            )
        elif plan.route == "compare" and len(market_snapshots) < 2:
            if resolved_tickers and unresolved_subjects:
                lines.append(
                    f"I could only resolve {', '.join(resolved_tickers)}. "
                    f"I couldn't resolve {', '.join(unresolved_subjects)} from that phrasing."
                )
                lines.append("Use the ticker symbol or a more specific company name and I'll compare them side by side.")
            else:
                lines.append("I need two ticker symbols or company names to run a comparison.")
        elif plan.route == "committee_review" and not resolved_tickers:
            if unresolved_subjects:
                lines.append(
                    f"I couldn't resolve {', '.join(unresolved_subjects)} to a tradeable ticker."
                )
            lines.append("I need a ticker or company name to generate bull, bear, and risk views.")
        elif plan.route == "portfolio_analysis":
            lines.append("Portfolio analysis")
        elif plan.route == "opportunity_suggestion":
            lines.append("Opportunity scan")
        elif plan.route == "committee_review":
            lines.append("Committee view")
        elif plan.route == "trade_preview":
            lines.append("Trade context")
        elif plan.route == "compare":
            lines.append("Comparison")
        else:
            if not market_snapshots and not research:
                lines.append("I can help with research or execution previews, but I need a ticker or company name to do something specific.")
            else:
                lines.append("Research summary")

        if isinstance(selection_summary, dict) and selection_summary.get("winner_ticker"):
            reason = selection_summary.get("reason")
            winner = selection_summary["winner_ticker"]
            line = f"Strongest candidate: {winner}"
            if plan.time_horizon:
                line += f" over the next {plan.time_horizon}"
            if reason:
                line += f" ({reason})"
            lines.append(line)

        for snapshot in market_snapshots[:3]:
            ticker = snapshot.get("ticker") or "Unknown"
            company = snapshot.get("company_name") or ticker
            price = snapshot.get("current_price")
            rs = snapshot.get("relative_strength_6m")
            rsi = snapshot.get("rsi_14")
            lines.append(f"{ticker} ({company})")
            if price is not None:
                lines.append(f"- Price: ${float(price):.2f}")
            if rs is not None:
                lines.append(f"- Relative strength 6m: {float(rs):.2f}")
            if rsi is not None:
                lines.append(f"- RSI(14): {float(rsi):.1f}")

        if research:
            lines.append("Recent research")
            for item in research[:4]:
                lines.append(f"- {item.get('title') or item.get('summary') or 'Untitled source'}")

        if related:
            labels = [str(item.get("ticker") or item.get("label") or "") for item in related[:4]]
            labels = [label for label in labels if label]
            if labels:
                lines.append(f"Related names: {', '.join(labels)}")

        if committee:
            lines.append("Analyst views")
            for item in committee[:3]:
                role = item.get("role") or "analyst"
                summary = item.get("summary") or item.get("thesis") or ""
                if summary:
                    lines.append(f"- {role}: {summary}")

        next_actions = list(evidence_bundle.get("next_actions") or plan.next_actions)
        return {
            "assistant_text": "\n".join(lines),
            "confidence": evidence_bundle.get("confidence", plan.confidence),
            "next_actions": next_actions,
            "warnings": warnings,
        }

    def _annotate_planner_fallback(self, decision: ChatPlannerDecision, reason: str) -> ChatPlannerDecision:
        return replace(decision, explanation=f"{decision.explanation} {reason}".strip())

    def _append_warning(self, payload: dict[str, Any], code: str, message: str) -> dict[str, Any]:
        warnings = list(payload.get("warnings") or [])
        warnings.append({"code": code, "message": message, "severity": "warning"})
        payload["warnings"] = warnings
        return payload

    def _openai_json_response(
        self,
        *,
        purpose: str,
        cycle_id: str,
        instructions: str,
        payload: dict[str, Any],
        max_output_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        client = openai.OpenAI(api_key=self.settings.openai_api_key_optional)
        response = client.responses.create(
            model=self.settings.conversation_planner_model,
            instructions=instructions,
            input=json.dumps(payload),
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )
        usage = response.usage
        if usage:
            log_cost(
                provider=Provider.OPENAI.value,
                model=self.settings.conversation_planner_model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cycle_id=cycle_id,
                purpose=purpose,
            )
        content = self._extract_json_text(response)
        return json.loads(content)

    def _extract_json_text(self, response: Any) -> str:
        content = str(getattr(response, "output_text", "") or "").strip()
        if not content:
            raise ValueError("Responses API returned no output text")
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        return content.strip()
