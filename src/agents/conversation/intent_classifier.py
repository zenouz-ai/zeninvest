"""Deterministic intent classifier for conversational trading.

Consolidates four overlapping regex classification layers into a single
three-tier classifier:
  Layer 1 — Regex patterns (<1ms, zero cost)
  Layer 2 — Keyword + context heuristics (<5ms, zero cost)
  Layer 3 — LLM fallback (only when L1+L2 return ambiguous)

Replaces:
  - orchestrator._classify_intent() regex constants
  - planner._heuristic_plan() regex constants
  - trade_command_parser._try_regex() (reused, not duplicated)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.agents.conversation.compare_parser import parse_compare_request
from src.agents.notifications.trade_command_parser import (
    TradeCommandIntent,
    parse_trade_command,
)
from src.utils.logger import get_logger

logger = get_logger("intent_classifier")

# ---------------------------------------------------------------------------
# Layer 1 — Regex patterns (moved from orchestrator.py + planner.py)
# ---------------------------------------------------------------------------

# Stop-loss update: "set stop for AAPL to $150"
STOP_UPDATE_RE = re.compile(
    r"^\s*(?:set|update|move|raise|lower)\s+(?:the\s+)?stop(?:-loss)?(?:\s+(?:for|on))?\s+"
    r"(?P<subject>.+?)\s+(?:to|at)\s+\$?(?P<price>\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)

# Portfolio value rule: "liquidate all holdings below £100"
PORTFOLIO_VALUE_RE = re.compile(
    r"^\s*(?:liquidate|sell)\s+(?:all\s+)?(?:tickers|holdings|positions)\s+(?:with\s+)?(?:holding\s+|value\s+)?"
    r"(?:below|under)\s+[£$]?(?P<threshold>\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)

# Portfolio PnL rule: "liquidate all losers below -5%"
PORTFOLIO_PNL_RE = re.compile(
    r"^\s*(?:liquidate|sell)\s+(?:all\s+)?(?P<bucket>winners|losers)\s+"
    r"(?:(?:above|over|below|under|worse\s+than|better\s+than)\s+)?(?P<threshold>-?\d+(?:\.\d+)?)%?\s*$",
    re.IGNORECASE,
)

# Confirm / reject keywords
CONFIRM_WORDS = frozenset({"yes", "y", "confirm", "approved", "do it", "go ahead"})
REJECT_WORDS = frozenset({"no", "n", "reject", "cancel", "stop"})

# ---------------------------------------------------------------------------
# Layer 2 — Keyword / heuristic patterns (moved from planner.py + orchestrator.py)
# ---------------------------------------------------------------------------

COMPARE_HINT_RE = re.compile(r"\b(compare|contrast|versus|vs\.?)\b", re.IGNORECASE)
COMMITTEE_HINT_RE = re.compile(r"\b(bull|bear|risk|committee|debate|pros and cons)\b", re.IGNORECASE)
PORTFOLIO_HINT_RE = re.compile(r"\b(portfolio|holdings|exposure|allocation|positions)\b", re.IGNORECASE)
OPPORTUNITY_HINT_RE = re.compile(
    r"\b(interesting|ideas|opportunities|what should i buy|stronger one|best in this space)\b",
    re.IGNORECASE,
)
RESEARCH_HINT_RE = re.compile(
    r"\b(compare|research|analyze|analysis|what about|how about|tell me about|look into|dig deeper|explain)\b",
    re.IGNORECASE,
)
GREETING_HINT_RE = re.compile(r"^\s*(hi|hello|hey|thanks|thank you)\b", re.IGNORECASE)
HELP_HINT_RE = re.compile(
    r"\b(help|how does this work|how this works|understand this workflow|what can you do|what does this do)\b",
    re.IGNORECASE,
)
PEER_SCAN_HINT_RE = re.compile(
    r"\b(related|peer|peers|adjacent|stronger|best in this space|what else|other names|nearby names)\b",
    re.IGNORECASE,
)

# Research prefix for subject extraction (from orchestrator.py)
RESEARCH_PREFIX_RE = re.compile(
    r"^\s*(?:compare|contrast|what about|how about|tell me about|research|look into|explain|dig deeper on"
    r"|happening with|show me|give me|views on|thoughts on|pros and cons of|bull and bear views on"
    r"|committee view on)\s+",
    re.IGNORECASE,
)

# Committee subject extraction (from orchestrator.py)
COMMITTEE_SUBJECT_RE = re.compile(
    r"\b(?:views?|bull and bear views?|committee view|pros and cons)\s+(?:on|for|about)\s+(?P<subject>.+?)\s*$",
    re.IGNORECASE,
)

# Generic "on/for/about <subject>" suffix
TARGET_SUFFIX_RE = re.compile(r"\b(?:on|for|about)\s+(?P<subject>.+?)\s*$", re.IGNORECASE)

# Follow-up context cues (pronouns, implicit references)
FOLLOW_UP_CONTEXT_RE = re.compile(
    r"\b(what about|how about|dig deeper|tell me more|tell me about it|explain more|that one|those|them|it)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# ClassifiedIntent dataclass
# ---------------------------------------------------------------------------

@dataclass
class ClassifiedIntent:
    """Result of intent classification.

    Attributes:
        intent_type: One of: trade_command, cancel, review, update_stop,
            portfolio_rule, compare, committee, research, portfolio_query,
            opportunity, help, greeting, confirm, reject, ambiguous
        confidence: 0.0 to 1.0
        method: "regex", "heuristic", or "llm"
        payload: Intent-specific data (e.g. TradeCommandIntent, stop price, etc.)
    """

    intent_type: str
    confidence: float
    method: str
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def is_deterministic(self) -> bool:
        """Whether this was classified without an LLM call."""
        return self.method in ("regex", "heuristic")

    @property
    def is_actionable(self) -> bool:
        """Whether this intent maps to a concrete handler (not ambiguous/greeting/help)."""
        return self.intent_type not in ("ambiguous", "greeting", "help")


# ---------------------------------------------------------------------------
# IntentClassifier
# ---------------------------------------------------------------------------

class IntentClassifier:
    """Three-layer deterministic intent classifier.

    Layer 1 — Regex: Exact command patterns (<1ms, confidence 0.85-0.95).
    Layer 2 — Keyword heuristics: Topic detection (<5ms, confidence 0.55-0.85).
    Layer 3 — LLM fallback: Only when L1+L2 return ambiguous (gated on budget).
    """

    def classify(
        self,
        message_text: str,
        context: dict[str, Any] | None = None,
        *,
        requested_mode: str | None = None,
    ) -> ClassifiedIntent:
        """Classify a user message into a structured intent.

        Args:
            message_text: The raw user message.
            context: Session context dict (may contain last_subject_tickers, etc.).
            requested_mode: Operator-selected mode override (quick/research/committee/trade).

        Returns:
            ClassifiedIntent with type, confidence, method, and payload.
        """
        context = context or {}
        text = (message_text or "").strip()
        if not text:
            return ClassifiedIntent(
                intent_type="ambiguous",
                confidence=0.0,
                method="regex",
                payload={"reason": "empty_message"},
            )

        # Layer 1: Regex patterns
        result = self._classify_regex(text, context)
        if result is not None:
            return result

        # Layer 2: Keyword + context heuristics
        result = self._classify_heuristic(text, context, requested_mode=requested_mode)
        if result is not None:
            return result

        # Fallback: ambiguous
        return ClassifiedIntent(
            intent_type="ambiguous",
            confidence=0.40,
            method="heuristic",
            payload={"reason": "no_pattern_matched"},
        )

    # ------------------------------------------------------------------
    # Layer 1 — Regex (zero cost, <1ms)
    # ------------------------------------------------------------------

    def _classify_regex(
        self,
        text: str,
        context: dict[str, Any],
    ) -> ClassifiedIntent | None:
        normalized = text.lower().strip()

        # Confirm / reject (highest priority — these are action completions)
        if normalized in CONFIRM_WORDS:
            return ClassifiedIntent(
                intent_type="confirm",
                confidence=0.99,
                method="regex",
                payload={"raw": text},
            )
        if normalized in REJECT_WORDS:
            return ClassifiedIntent(
                intent_type="reject",
                confidence=0.99,
                method="regex",
                payload={"raw": text},
            )

        # Stop-loss update: "set stop for AAPL to $150"
        stop_match = STOP_UPDATE_RE.match(text)
        if stop_match:
            return ClassifiedIntent(
                intent_type="update_stop",
                confidence=0.90,
                method="regex",
                payload={
                    "subject": stop_match.group("subject"),
                    "stop_price": float(stop_match.group("price")),
                },
            )

        # Portfolio value rule: "liquidate holdings below £100"
        portfolio_value_match = PORTFOLIO_VALUE_RE.match(text)
        if portfolio_value_match:
            return ClassifiedIntent(
                intent_type="portfolio_rule",
                confidence=0.90,
                method="regex",
                payload={
                    "rule": "value_below",
                    "threshold": float(portfolio_value_match.group("threshold")),
                },
            )

        # Portfolio PnL rule: "liquidate all losers below -5%"
        pnl_match = PORTFOLIO_PNL_RE.match(text)
        if pnl_match:
            bucket = pnl_match.group("bucket").lower()
            threshold = float(pnl_match.group("threshold"))
            if bucket == "losers" and threshold > 0:
                threshold = -threshold
            if bucket == "winners" and threshold < 0:
                threshold = abs(threshold)
            return ClassifiedIntent(
                intent_type="portfolio_rule",
                confidence=0.90,
                method="regex",
                payload={
                    "rule": "pnl_threshold",
                    "bucket": bucket,
                    "threshold": threshold,
                },
            )

        # Trade commands (BUY/SELL/REVIEW/CANCEL) — delegates to existing parser
        trade_intent = parse_trade_command(text, use_llm_fallback=False)
        if trade_intent is not None:
            intent_type = {
                "cancel": "cancel",
                "review": "review",
            }.get(trade_intent.command_kind, "trade_command")
            return ClassifiedIntent(
                intent_type=intent_type,
                confidence=0.95,
                method="regex",
                payload={"trade_intent": trade_intent},
            )

        # Compare requests: "compare NVDA vs AMD"
        compare_request = parse_compare_request(text)
        if compare_request is not None:
            return ClassifiedIntent(
                intent_type="compare",
                confidence=0.88,
                method="regex",
                payload={"compare_request": compare_request},
            )

        if re.search(r"\b(buy|sell|review|cancel)\b", text, re.IGNORECASE) and not COMPARE_HINT_RE.search(text):
            trade_intent = parse_trade_command(text, use_llm_fallback=True)
            if trade_intent is not None:
                intent_type = {
                    "cancel": "cancel",
                    "review": "review",
                }.get(trade_intent.command_kind, "trade_command")
                return ClassifiedIntent(
                    intent_type=intent_type,
                    confidence=0.78,
                    method="llm",
                    payload={"trade_intent": trade_intent},
                )

        return None

    # ------------------------------------------------------------------
    # Layer 2 — Keyword + context heuristics (zero cost, <5ms)
    # ------------------------------------------------------------------

    def _classify_heuristic(
        self,
        text: str,
        context: dict[str, Any],
        *,
        requested_mode: str | None = None,
    ) -> ClassifiedIntent | None:
        normalized = text.strip()

        # Greeting
        if GREETING_HINT_RE.search(normalized):
            return ClassifiedIntent(
                intent_type="greeting",
                confidence=0.95,
                method="heuristic",
                payload={"raw": text},
            )

        # Help / system guidance
        if HELP_HINT_RE.search(normalized):
            return ClassifiedIntent(
                intent_type="help",
                confidence=0.90,
                method="heuristic",
                payload={"raw": text},
            )

        # Compare hint (weaker than regex compare — e.g. "compare these two")
        if COMPARE_HINT_RE.search(normalized):
            return ClassifiedIntent(
                intent_type="compare",
                confidence=0.78,
                method="heuristic",
                payload={"raw": text},
            )

        # Portfolio query
        if PORTFOLIO_HINT_RE.search(normalized):
            return ClassifiedIntent(
                intent_type="portfolio_query",
                confidence=0.75,
                method="heuristic",
                payload={"raw": text},
            )

        # Opportunity suggestion
        if OPPORTUNITY_HINT_RE.search(normalized):
            return ClassifiedIntent(
                intent_type="opportunity",
                confidence=0.76,
                method="heuristic",
                payload={"raw": text},
            )

        # Committee / analyst views
        if COMMITTEE_HINT_RE.search(normalized):
            return ClassifiedIntent(
                intent_type="committee",
                confidence=0.74,
                method="heuristic",
                payload={"raw": text},
            )

        # Explicit trade mode request (operator selected mode=trade but message isn't a command)
        if requested_mode == "trade":
            return ClassifiedIntent(
                intent_type="trade_command",
                confidence=0.68,
                method="heuristic",
                payload={"raw": text, "inferred_from_mode": True},
            )

        # Research-style question or follow-up context
        if RESEARCH_HINT_RE.search(normalized):
            is_peer_scan = PEER_SCAN_HINT_RE.search(normalized) is not None
            return ClassifiedIntent(
                intent_type="research",
                confidence=0.75,
                method="heuristic",
                payload={"raw": text, "is_peer_scan": is_peer_scan},
            )

        # Follow-up context cue with existing session tickers
        if context.get("last_subject_tickers") and FOLLOW_UP_CONTEXT_RE.search(normalized):
            return ClassifiedIntent(
                intent_type="research",
                confidence=0.70,
                method="heuristic",
                payload={
                    "raw": text,
                    "follow_up": True,
                    "context_tickers": list(context["last_subject_tickers"]),
                },
            )

        return None
