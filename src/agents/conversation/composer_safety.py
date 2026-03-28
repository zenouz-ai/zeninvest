"""Post-composition safety check for conversational trading (US-1.9 Phase 5).

Ensures that high-severity risk warnings from bear/risk specialist views
are not silently dropped during the LLM composition step.
"""

from __future__ import annotations

import re
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("composer_safety")

# Risk-signal keywords to check for in composed output
_RISK_KEYWORDS = frozenset({
    "risk", "downside", "caution", "warning", "concern",
    "overvalued", "decline", "loss", "bearish", "volatility",
    "headwind", "recession", "debt", "leverage", "bubble",
    "correction", "selloff", "sell-off", "negative", "danger",
    "deteriorat", "weakness", "regulatory",
})

# Phrases that indicate the composed output has adequately addressed risk
_RISK_ACKNOWLEDGMENT_PATTERNS = [
    re.compile(r"\brisk[s]?\b", re.I),
    re.compile(r"\bcaution\b", re.I),
    re.compile(r"\bdownside\b", re.I),
    re.compile(r"\bbearish\b", re.I),
    re.compile(r"\bwarning\b", re.I),
    re.compile(r"\bconcern\b", re.I),
    re.compile(r"\bvolatil", re.I),
    re.compile(r"\bheadwind\b", re.I),
    re.compile(r"\bovervalue\b", re.I),
]

# Routes that bypass safety checks (pure data, no committee involvement)
_BYPASS_ROUTES = frozenset({
    "portfolio_analysis",
    "quick_answer",
    "greeting",
    "help",
    "portfolio_query",
})


def extract_risk_signals(committee_views: list[dict[str, Any]]) -> list[str]:
    """Extract significant risk signals from bear and risk specialist views.

    Returns a list of warning strings that the composed output should address.
    """
    signals: list[str] = []
    for view in committee_views:
        if not isinstance(view, dict):
            continue
        role = (view.get("role") or "").lower()
        if role not in ("bear", "risk"):
            continue

        stance = (view.get("stance") or "").lower()
        summary = view.get("summary") or ""

        # High-severity: bearish or cautious stance
        if stance in ("bearish", "cautious", "negative", "high_risk"):
            signals.append(summary[:300] if len(summary) > 300 else summary)
        # Medium-severity: any warning keywords in summary
        elif summary:
            summary_lower = summary.lower()
            if any(kw in summary_lower for kw in _RISK_KEYWORDS):
                signals.append(summary[:200] if len(summary) > 200 else summary)

    return signals


def check_risk_coverage(
    assistant_text: str,
    risk_signals: list[str],
) -> list[str]:
    """Check whether the composed assistant text adequately covers the risk signals.

    Returns a list of uncovered risk signal summaries (empty if all covered).
    """
    if not risk_signals or not assistant_text:
        return []

    text_lower = assistant_text.lower()

    # Check if the composed text has any risk acknowledgment
    has_any_risk_mention = any(p.search(assistant_text) for p in _RISK_ACKNOWLEDGMENT_PATTERNS)
    if has_any_risk_mention:
        return []

    # No risk acknowledgment at all — all signals are uncovered
    return risk_signals


def build_risk_appendix(uncovered_signals: list[str]) -> str:
    """Build a brief risk note to append when warnings were dropped."""
    if not uncovered_signals:
        return ""
    if len(uncovered_signals) == 1:
        return f"\n\n**Risk note:** {uncovered_signals[0]}"
    # Multiple signals — combine into a compact list
    items = "\n".join(f"- {s}" for s in uncovered_signals[:3])
    return f"\n\n**Risk notes:**\n{items}"


def apply_safety_check(
    assistant_text: str,
    evidence_bundle: dict[str, Any],
    route: str | None = None,
) -> str:
    """Apply post-composition safety check and return (possibly augmented) text.

    Parameters
    ----------
    assistant_text : str
        The composed assistant response.
    evidence_bundle : dict
        The evidence bundle containing ``committee_views``.
    route : str | None
        The planner route. Some routes bypass safety checks.

    Returns
    -------
    str
        The assistant text, possibly with appended risk notes.
    """
    # Bypass for pure data/greeting routes
    if route and route in _BYPASS_ROUTES:
        return assistant_text

    committee_views = evidence_bundle.get("committee_views") or []
    if not committee_views:
        return assistant_text

    risk_signals = extract_risk_signals(committee_views)
    if not risk_signals:
        return assistant_text

    uncovered = check_risk_coverage(assistant_text, risk_signals)
    if not uncovered:
        return assistant_text

    appendix = build_risk_appendix(uncovered)
    if appendix:
        logger.warning(
            "Composer safety: %d risk signal(s) not covered in composed output, appending notes",
            len(uncovered),
        )
        return assistant_text + appendix

    return assistant_text
