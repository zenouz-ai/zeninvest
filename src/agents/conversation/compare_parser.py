"""Structured parser for compare-style conversational requests."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from src.agents.notifications.trade_command_parser import TradeCommandIntent, parse_trade_command

_COMPARE_PREFIX_RE = re.compile(r"^\s*(?:compare|contrast)\s+", re.IGNORECASE)
_THEN_SPLIT_RE = re.compile(r"\s*,?\s+then\s+", re.IGNORECASE)
_VS_SPLIT_RE = re.compile(r"\s+(?:vs\.?|versus)\s+", re.IGNORECASE)
_TIME_HORIZON_RE = re.compile(
    r"\b(?:over|for)\s+(?:the\s+next\s+)?(?P<horizon>\d+(?:\s*-\s*\d+)?\s+"
    r"(?:hour|hours|day|days|week|weeks|month|months|year|years))\b",
    re.IGNORECASE,
)
_PICK_STRONGEST_RE = re.compile(
    r"\b(strongest|stronger|best setup|best in this space|better buy|which looks strongest|which is strongest)\b",
    re.IGNORECASE,
)
_WINNER_PLACEHOLDER_RE = re.compile(
    r"\b(the\s+)?(stronger|strongest|winner|best)\s+(one|name|ticker|stock)\b|\b(the\s+)?winner\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class CompareRequest:
    """Normalized compare request details shared across planner and orchestrator."""

    subjects: list[str]
    comparison_goal: str = "compare"
    time_horizon: str | None = None
    follow_up_text: str | None = None
    post_compare_trade_intent: TradeCommandIntent | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.post_compare_trade_intent is not None:
            payload["post_compare_trade_intent"] = asdict(self.post_compare_trade_intent)
        return payload


def parse_compare_request(message_text: str) -> CompareRequest | None:
    """Parse compare prompts with 2-3 subjects and optional follow-up intent."""

    cleaned = " ".join((message_text or "").strip().split())
    if not cleaned or not _COMPARE_PREFIX_RE.match(cleaned):
        return None

    compare_body = _COMPARE_PREFIX_RE.sub("", cleaned, count=1).strip()
    follow_up_text = None
    split = _THEN_SPLIT_RE.split(compare_body, maxsplit=1)
    if len(split) == 2:
        compare_body, follow_up_text = split[0].strip(), split[1].strip()

    subjects = _split_compare_subjects(compare_body)
    if not 2 <= len(subjects) <= 3:
        return None

    time_horizon = None
    comparison_goal = "compare"
    if follow_up_text:
        time_match = _TIME_HORIZON_RE.search(follow_up_text)
        if time_match:
            time_horizon = " ".join(time_match.group("horizon").split())
        if _PICK_STRONGEST_RE.search(follow_up_text):
            comparison_goal = "pick_strongest"

    post_compare_trade_intent = None
    if follow_up_text:
        parsed_intent = parse_trade_command(follow_up_text, use_llm_fallback=False)
        if parsed_intent is not None:
            post_compare_trade_intent = parsed_intent
            if _targets_comparison_winner(parsed_intent):
                comparison_goal = "pick_strongest"

    return CompareRequest(
        subjects=subjects,
        comparison_goal=comparison_goal,
        time_horizon=time_horizon,
        follow_up_text=follow_up_text,
        post_compare_trade_intent=post_compare_trade_intent,
    )


def retarget_trade_intent_to_winner(intent: TradeCommandIntent, winner_ticker: str, *, raw_message: str) -> TradeCommandIntent:
    """Clone a follow-up trade intent so it targets the selected winner."""

    updated_subjects = []
    for subject in intent.subject_phrases or []:
        updated_subjects.append(winner_ticker if _WINNER_PLACEHOLDER_RE.search(subject) else subject)
    if not updated_subjects:
        updated_subjects = [winner_ticker]

    return TradeCommandIntent(
        action=intent.action,
        ticker=winner_ticker,
        quantity_shares=intent.quantity_shares,
        amount_gbp=intent.amount_gbp,
        raw_message=raw_message,
        force=intent.force,
        command_kind=intent.command_kind,
        execution_mode=intent.execution_mode,
        trigger_strategy=intent.trigger_strategy,
        cancel_order_class=intent.cancel_order_class,
        subject_phrases=updated_subjects,
    )


def _split_compare_subjects(compare_body: str) -> list[str]:
    normalized = compare_body.strip(" ,.;:!?")
    normalized = _VS_SPLIT_RE.sub(", ", normalized)
    normalized = re.sub(r",?\s+and\s+", ", ", normalized, flags=re.IGNORECASE)
    parts = [" ".join(part.split()).strip(" ,.;:!?") for part in normalized.split(",")]
    return [part for part in parts if part]


def _targets_comparison_winner(intent: TradeCommandIntent) -> bool:
    return any(_WINNER_PLACEHOLDER_RE.search(subject or "") for subject in intent.subject_phrases or [])
