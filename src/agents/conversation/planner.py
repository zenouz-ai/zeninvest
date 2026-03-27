"""Planner and composer for agentic conversational trading."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import openai

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
            or requested_mode == "quick"
        ):
            return heuristic

        if not self.settings.openai_api_key_optional:
            return heuristic
        if not check_budget(Provider.OPENAI.value):
            return heuristic

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
            return heuristic

    def compose_response(
        self,
        *,
        user_message: str,
        plan: ChatPlannerDecision,
        evidence_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        fallback = self._compose_fallback(plan=plan, evidence_bundle=evidence_bundle)
        if (
            not self.settings.conversation_agentic_planner_enabled
            or not self.settings.openai_api_key_optional
            or not check_budget(Provider.OPENAI.value)
            or os.getenv("INVESTMENT_AGENT_USE_INMEMORY_DB") == "1"
        ):
            return fallback

        try:
            client = openai.OpenAI(api_key=self.settings.openai_api_key_optional)
            response = client.chat.completions.create(
                model=self.settings.conversation_planner_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are the single operator-facing assistant for an investment system. "
                            "Write concise, source-aware replies. Never reveal hidden reasoning. "
                            "If evidence is incomplete, say so. Respond with JSON only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "user_message": user_message,
                                "route": plan.route,
                                "turn_mode": plan.turn_mode,
                                "evidence_bundle": evidence_bundle,
                            }
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.35,
                max_tokens=1400,
            )
            usage = response.usage
            if usage:
                log_cost(
                    provider=Provider.OPENAI.value,
                    model=self.settings.conversation_planner_model,
                    input_tokens=usage.prompt_tokens,
                    output_tokens=usage.completion_tokens,
                    cycle_id=f"chat-compose-{plan.route}",
                    purpose="conversation_composer",
                )
            content = response.choices[0].message.content or "{}"
            parsed = json.loads(content)
            assistant_text = str(parsed.get("assistant_text") or "").strip()
            next_actions = parsed.get("next_actions")
            if not assistant_text:
                return fallback
            return {
                "assistant_text": assistant_text,
                "confidence": parsed.get("confidence", evidence_bundle.get("confidence")),
                "next_actions": next_actions if isinstance(next_actions, list) else fallback["next_actions"],
            }
        except Exception as exc:
            logger.warning("Composer fell back to deterministic rendering: %s", exc, exc_info=True)
            return fallback

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

        if requested_mode == "committee":
            return ChatPlannerDecision(
                route="committee_review",
                turn_mode="committee",
                use_fast_path=False,
                requires_web_research=True,
                requires_related_scan=COMPARE_HINT_RE.search(normalized) is not None,
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
            )
        if COMMITTEE_HINT_RE.search(normalized):
            return ChatPlannerDecision(
                route="committee_review",
                turn_mode=requested_mode or "committee",
                use_fast_path=False,
                requires_web_research=True,
                requires_related_scan=COMPARE_HINT_RE.search(normalized) is not None,
                requires_committee=True,
                requires_trade_preview=False,
                should_suggest_opportunity=False,
                confidence=0.74,
                next_actions=["preview trade", "show related tickers", "compare peers"],
                explanation="User asked for explicit analyst-style viewpoints.",
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
            )
        if RESEARCH_HINT_RE.search(normalized) or context.get("last_subject_tickers"):
            route = "related_ticker_scan" if "related" in lowered or "stronger" in lowered else "grounded_research"
            return ChatPlannerDecision(
                route=route,
                turn_mode=requested_mode or "research",
                use_fast_path=False,
                requires_web_research=True,
                requires_related_scan=route == "related_ticker_scan" or COMPARE_HINT_RE.search(normalized) is not None,
                requires_committee=requested_mode == "committee",
                requires_trade_preview=False,
                should_suggest_opportunity=route == "related_ticker_scan" and "stronger" in lowered,
                confidence=0.71,
                next_actions=["compare peers", "show sources", "preview trade"],
                explanation="Substantive research-style question.",
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
        client = openai.OpenAI(api_key=self.settings.openai_api_key_optional)
        response = client.chat.completions.create(
            model=self.settings.conversation_planner_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the route planner for an audited investment-operations chat. "
                        "Choose the minimum route that still answers the request well. "
                        "Never permit direct trade execution. Respond with JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message_text": message_text,
                            "requested_mode": requested_mode,
                            "budget_tier": budget_tier,
                            "context": {
                                "last_subject_tickers": context.get("last_subject_tickers") or [],
                                "last_selection_tickers": context.get("last_selection_tickers") or [],
                            },
                            "heuristic_default": heuristic.as_dict(),
                            "allowed_routes": [
                                "quick_answer",
                                "grounded_research",
                                "related_ticker_scan",
                                "committee_review",
                                "portfolio_analysis",
                                "trade_preview",
                                "opportunity_suggestion",
                            ],
                        }
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=900,
        )
        usage = response.usage
        if usage:
            log_cost(
                provider=Provider.OPENAI.value,
                model=self.settings.conversation_planner_model,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                cycle_id="chat-plan",
                purpose="conversation_planner",
            )

        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
        route = str(payload.get("route") or heuristic.route)
        turn_mode = str(payload.get("turn_mode") or requested_mode or heuristic.turn_mode)
        next_actions = payload.get("next_actions")
        return ChatPlannerDecision(
            route=route,
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
        )

    def _compose_fallback(self, *, plan: ChatPlannerDecision, evidence_bundle: dict[str, Any]) -> dict[str, Any]:
        market_snapshots = evidence_bundle.get("market_snapshot") or []
        research = evidence_bundle.get("news_findings") or []
        related = evidence_bundle.get("related_tickers") or []
        committee = evidence_bundle.get("committee_views") or []
        lines = []
        if plan.route == "portfolio_analysis":
            lines.append("Portfolio analysis")
        elif plan.route == "opportunity_suggestion":
            lines.append("Opportunity scan")
        elif plan.route == "committee_review":
            lines.append("Committee view")
        elif plan.route == "trade_preview":
            lines.append("Trade context")
        else:
            lines.append("Research summary")

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
        }
