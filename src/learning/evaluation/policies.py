"""Canonical champion/challenger policy identifiers."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

RecommendedAction = Literal["buy", "queue", "skip", "reduce_conviction", "prioritize"]


class PolicyId(StrEnum):
    CHAMPION_AS_IS = "champion_as_is"
    BASELINE_CONVICTION = "baseline_conviction"
    CHALLENGER_GBM = "challenger_gbm"
    CHALLENGER_CALIBRATOR = "challenger_calibrator"
    CHALLENGER_RL = "challenger_rl"
    CHALLENGER_MEMORY = "challenger_memory"
    CHALLENGER_COMBINED = "challenger_combined"


ALL_POLICIES: tuple[PolicyId, ...] = tuple(PolicyId)

DEFAULT_EVAL_POLICIES: tuple[PolicyId, ...] = (
    PolicyId.CHAMPION_AS_IS,
    PolicyId.BASELINE_CONVICTION,
    PolicyId.CHALLENGER_GBM,
    PolicyId.CHALLENGER_MEMORY,
    PolicyId.CHALLENGER_COMBINED,
)

DEFAULT_SHADOW_POLICIES: tuple[PolicyId, ...] = (
    PolicyId.CHALLENGER_GBM,
    PolicyId.CHALLENGER_MEMORY,
    PolicyId.CHALLENGER_COMBINED,
)

BAD_LABELS: frozenset[str] = frozenset({"big_loser", "stall"})
