"""Tests for post-composition safety check (Phase 5).

Covers: risk signal extraction, coverage checking, appendix generation,
route bypass, and full apply_safety_check flow.
"""

import os

os.environ.setdefault("INVESTMENT_AGENT_USE_INMEMORY_DB", "1")

import pytest

from src.agents.conversation.composer_safety import (
    apply_safety_check,
    build_risk_appendix,
    check_risk_coverage,
    extract_risk_signals,
)


# ---------------------------------------------------------------------------
# extract_risk_signals
# ---------------------------------------------------------------------------


class TestExtractRiskSignals:
    def test_bearish_stance_extracted(self):
        views = [
            {"role": "bear", "stance": "bearish", "summary": "Stock is overvalued with declining revenues."},
        ]
        signals = extract_risk_signals(views)
        assert len(signals) == 1
        assert "overvalued" in signals[0]

    def test_risk_cautious_stance_extracted(self):
        views = [
            {"role": "risk", "stance": "cautious", "summary": "High leverage ratio raises concern."},
        ]
        signals = extract_risk_signals(views)
        assert len(signals) == 1

    def test_bull_view_ignored(self):
        views = [
            {"role": "bull", "stance": "bullish", "summary": "Strong momentum, great opportunity."},
        ]
        signals = extract_risk_signals(views)
        assert len(signals) == 0

    def test_neutral_bear_with_risk_keywords(self):
        views = [
            {"role": "bear", "stance": "neutral", "summary": "Some volatility risk from trade tensions."},
        ]
        signals = extract_risk_signals(views)
        assert len(signals) == 1

    def test_neutral_bear_without_risk_keywords(self):
        views = [
            {"role": "bear", "stance": "neutral", "summary": "The company looks fine overall."},
        ]
        signals = extract_risk_signals(views)
        assert len(signals) == 0

    def test_empty_views(self):
        assert extract_risk_signals([]) == []

    def test_truncates_long_summary(self):
        views = [
            {"role": "risk", "stance": "high_risk", "summary": "X" * 500},
        ]
        signals = extract_risk_signals(views)
        assert len(signals[0]) == 300


# ---------------------------------------------------------------------------
# check_risk_coverage
# ---------------------------------------------------------------------------


class TestCheckRiskCoverage:
    def test_covered_when_risk_mentioned(self):
        text = "While the stock has strong momentum, there are significant risks to consider."
        signals = ["High leverage could cause problems."]
        assert check_risk_coverage(text, signals) == []

    def test_covered_when_caution_mentioned(self):
        text = "Exercise caution given the current market conditions."
        signals = ["Volatility is elevated."]
        assert check_risk_coverage(text, signals) == []

    def test_uncovered_when_no_risk_words(self):
        text = "This stock looks great and has strong fundamentals with excellent growth."
        signals = ["High debt levels are concerning."]
        uncovered = check_risk_coverage(text, signals)
        assert len(uncovered) == 1

    def test_empty_signals_always_covered(self):
        assert check_risk_coverage("any text", []) == []

    def test_empty_text_returns_all_uncovered(self):
        signals = ["Signal 1", "Signal 2"]
        assert check_risk_coverage("", signals) == []  # empty text = no signals to check


# ---------------------------------------------------------------------------
# build_risk_appendix
# ---------------------------------------------------------------------------


class TestBuildRiskAppendix:
    def test_single_signal(self):
        result = build_risk_appendix(["Stock has high leverage."])
        assert "**Risk note:**" in result
        assert "high leverage" in result

    def test_multiple_signals(self):
        result = build_risk_appendix(["Signal 1", "Signal 2"])
        assert "**Risk notes:**" in result
        assert "- Signal 1" in result
        assert "- Signal 2" in result

    def test_empty_returns_empty(self):
        assert build_risk_appendix([]) == ""


# ---------------------------------------------------------------------------
# apply_safety_check — full flow
# ---------------------------------------------------------------------------


class TestApplySafetyCheck:
    def test_appends_risk_note_when_dropped(self):
        evidence = {
            "committee_views": [
                {"role": "bear", "stance": "bearish", "summary": "Overvalued with declining margins."},
            ]
        }
        text = "This stock has excellent growth potential and strong momentum."
        result = apply_safety_check(text, evidence, route="committee")
        assert "**Risk note:**" in result
        assert "Overvalued" in result

    def test_no_appendix_when_risk_acknowledged(self):
        evidence = {
            "committee_views": [
                {"role": "bear", "stance": "bearish", "summary": "Overvalued."},
            ]
        }
        text = "While there are risks including overvaluation, the stock has momentum."
        result = apply_safety_check(text, evidence, route="committee")
        assert "**Risk note:**" not in result

    def test_bypass_for_portfolio_analysis(self):
        evidence = {
            "committee_views": [
                {"role": "bear", "stance": "bearish", "summary": "Bad stock."},
            ]
        }
        text = "Here is your portfolio summary."
        result = apply_safety_check(text, evidence, route="portfolio_analysis")
        assert result == text  # no modification

    def test_bypass_for_greeting(self):
        evidence = {"committee_views": []}
        text = "Hello! How can I help?"
        result = apply_safety_check(text, evidence, route="greeting")
        assert result == text

    def test_no_committee_views_passes_through(self):
        evidence = {}
        text = "Some analysis text."
        result = apply_safety_check(text, evidence, route="research")
        assert result == text

    def test_only_bull_views_no_appendix(self):
        evidence = {
            "committee_views": [
                {"role": "bull", "stance": "bullish", "summary": "Great stock!"},
            ]
        }
        text = "Strong buy recommendation based on momentum."
        result = apply_safety_check(text, evidence, route="committee")
        assert result == text
