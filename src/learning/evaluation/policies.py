"""Canonical champion/challenger policy identifiers."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

RecommendedAction = Literal["buy", "queue", "skip", "reduce_conviction", "prioritize"]


class PolicyId(StrEnum):
    CHAMPION_AS_IS = "champion_as_is"
    BASELINE_STRATEGY_ONLY = "baseline_strategy_only"
    BASELINE_CONVICTION = "baseline_conviction"
    CHALLENGER_MODERATION = "challenger_moderation"
    CHALLENGER_GPT_ONLY = "challenger_gpt_only"
    CHALLENGER_GEMINI_ONLY = "challenger_gemini_only"
    CHALLENGER_RISK_ONLY = "challenger_risk_only"
    CHALLENGER_GBM = "challenger_gbm"
    CHALLENGER_CALIBRATOR = "challenger_calibrator"
    CHALLENGER_RL = "challenger_rl"
    CHALLENGER_MEMORY = "challenger_memory"
    CHALLENGER_COMBINED = "challenger_combined"
    CHALLENGER_NO_RESEARCH = "challenger_no_research"
    CHALLENGER_SKEPTIC_RESEARCH = "challenger_skeptic_research"


RESEARCH_EVAL_POLICIES: tuple[PolicyId, ...] = (
    PolicyId.CHALLENGER_NO_RESEARCH,
    PolicyId.CHALLENGER_SKEPTIC_RESEARCH,
)

ALL_POLICIES: tuple[PolicyId, ...] = tuple(PolicyId)

COMMITTEE_EVAL_POLICIES: tuple[PolicyId, ...] = (
    PolicyId.BASELINE_STRATEGY_ONLY,
    PolicyId.CHALLENGER_MODERATION,
    PolicyId.CHALLENGER_GPT_ONLY,
    PolicyId.CHALLENGER_GEMINI_ONLY,
    PolicyId.CHALLENGER_RISK_ONLY,
)

DEFAULT_EVAL_POLICIES: tuple[PolicyId, ...] = (
    PolicyId.CHAMPION_AS_IS,
    *COMMITTEE_EVAL_POLICIES,
    *RESEARCH_EVAL_POLICIES,
    PolicyId.BASELINE_CONVICTION,
    PolicyId.CHALLENGER_GBM,
    PolicyId.CHALLENGER_CALIBRATOR,
    PolicyId.CHALLENGER_MEMORY,
    PolicyId.CHALLENGER_COMBINED,
)

DEFAULT_SHADOW_POLICIES: tuple[PolicyId, ...] = (
    PolicyId.CHALLENGER_GBM,
    PolicyId.CHALLENGER_MEMORY,
    PolicyId.CHALLENGER_COMBINED,
)

BAD_LABELS: frozenset[str] = frozenset({"big_loser", "stall"})
