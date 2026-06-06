"""Tests for the deterministic IntentClassifier.

Tests cover all three layers:
  Layer 1 — Regex: trade commands, stop updates, portfolio rules, confirm/reject
  Layer 2 — Heuristic: greetings, help, compare, research, follow-up context
  Layer 3 — Ambiguous fallback

Simple "message -> intent_type" expectations are consolidated into parametrized
tables (SIMPLE_INTENT_CASES); cases with richer payload/confidence/method
assertions keep dedicated tests below.
"""

import os

os.environ.setdefault("INVESTMENT_AGENT_USE_INMEMORY_DB", "1")

import pytest

from src.agents.conversation.intent_classifier import IntentClassifier


@pytest.fixture
def classifier():
    return IntentClassifier()


# ---------------------------------------------------------------------------
# Consolidated: simple message -> intent_type expectations
# (covers confirm/reject words, greetings, help, research/portfolio/committee/
#  opportunity/compare heuristics, and ambiguous fallbacks)
# ---------------------------------------------------------------------------

SIMPLE_INTENT_CASES = [
    # Layer 1 regex: confirm / reject
    ("yes", "confirm"),
    ("confirm", "confirm"),
    ("go ahead", "confirm"),
    ("no", "reject"),
    ("reject", "reject"),
    ("cancel", "reject"),
    # Layer 2 heuristic: greetings
    ("hello", "greeting"),
    ("hi", "greeting"),
    ("thanks", "greeting"),
    # Layer 2 heuristic: help
    ("help", "help"),
    ("what can you do", "help"),
    ("how does this work", "help"),
    # Layer 2 heuristic: research
    ("research ASML", "research"),
    ("tell me about Tesla", "research"),
    ("look into semiconductor sector", "research"),
    # Layer 2 heuristic: portfolio query
    ("how's my portfolio doing", "portfolio_query"),
    ("show me my positions", "portfolio_query"),
    ("what are my current holdings", "portfolio_query"),
    # Layer 2 heuristic: committee / bull-bear
    ("give me the bull and bear case for NVDA", "committee"),
    ("what are the risk factors for ASML", "committee"),
    ("pros and cons of investing in Tesla", "committee"),
    # Layer 2 heuristic: opportunity
    ("any interesting opportunities right now", "opportunity"),
    ("what should i buy", "opportunity"),
    # Layer 2 heuristic: weak compare (no structured CompareRequest)
    ("how does Apple versus Google look", "compare"),
    # Layer 1 regex: multi-ticker compare (intent only; subjects covered below)
    ("compare AAPL, MSFT and GOOG", "compare"),
    # Ambiguous / fallback
    ("", "ambiguous"),
    ("   ", "ambiguous"),
    ("the weather is nice today", "ambiguous"),
    (None, "ambiguous"),
]


@pytest.mark.parametrize("message,expected", SIMPLE_INTENT_CASES)
def test_simple_intent_classification(classifier, message, expected):
    assert classifier.classify(message).intent_type == expected


@pytest.mark.parametrize(
    "message,max_confidence", [("", 0.0), ("   ", 0.0), ("the weather is nice today", 0.50)]
)
def test_ambiguous_confidence_bounds(classifier, message, max_confidence):
    assert classifier.classify(message).confidence <= max_confidence


# ---------------------------------------------------------------------------
# Layer 1 — Regex: confidence + method contract on representative inputs
# (the layering/priority guarantees previously asserted by TestPriorityOrdering)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,intent_type,min_confidence",
    [
        ("yes", "confirm", 0.95),
        ("no", "reject", 0.95),
        ("buy AAPL", "trade_command", 0.90),
        ("review AAPL", "review", 0.0),
        ("compare NVDA and AMD", "compare", 0.80),
        ("set stop for AAPL to $150", "update_stop", 0.85),
        ("liquidate all holdings below £100", "portfolio_rule", 0.85),
    ],
)
def test_regex_layer_contract(classifier, message, intent_type, min_confidence):
    """Regex layer wins (method == 'regex') with high confidence — these inputs
    must not fall through to heuristic research/compare keywords."""
    result = classifier.classify(message)
    assert result.intent_type == intent_type
    assert result.method == "regex"
    assert result.confidence >= min_confidence


@pytest.mark.parametrize(
    "message,method,min_confidence",
    [("hello", "heuristic", 0.90), ("help", "heuristic", 0.0)],
)
def test_heuristic_layer_method(classifier, message, method, min_confidence):
    result = classifier.classify(message)
    assert result.method == method
    assert result.confidence >= min_confidence


# ---------------------------------------------------------------------------
# Layer 1 — Regex: Trade commands (payload-rich cases)
# ---------------------------------------------------------------------------


class TestTradeCommands:
    def test_buy_command(self, classifier):
        result = classifier.classify("buy AAPL")
        assert result.intent_type == "trade_command"
        assert result.payload["trade_intent"].action == "BUY"

    def test_sell_command(self, classifier):
        result = classifier.classify("sell MSFT")
        assert result.intent_type == "trade_command"
        assert result.payload["trade_intent"].action == "SELL"

    def test_buy_with_amount(self, classifier):
        result = classifier.classify("buy £500 AAPL")
        intent = result.payload["trade_intent"]
        assert intent.action == "BUY"
        assert intent.amount_gbp == 500.0

    def test_buy_with_quantity(self, classifier):
        result = classifier.classify("buy 10 shares of NVDA")
        intent = result.payload["trade_intent"]
        assert intent.action == "BUY"
        assert intent.quantity_shares == 10.0

    @pytest.mark.parametrize(
        "message", ["force buy AAPL", "override buy TSLA", "!buy AMZN"]
    )
    def test_force_variants_set_force(self, classifier, message):
        result = classifier.classify(message)
        assert result.intent_type == "trade_command"
        assert result.payload["trade_intent"].force is True

    def test_review_command(self, classifier):
        result = classifier.classify("review ASML")
        assert result.intent_type == "review"
        assert result.method == "regex"
        assert result.payload["trade_intent"].command_kind == "review"

    def test_review_and_buy(self, classifier):
        result = classifier.classify("review AAPL and buy")
        intent = result.payload["trade_intent"]
        assert result.intent_type == "trade_command"
        assert intent.action == "BUY"
        assert intent.execution_mode == "strategy"
        assert intent.trigger_strategy is True

    def test_cancel_buy_command(self, classifier):
        result = classifier.classify("cancel buy AAPL")
        assert result.intent_type == "cancel"
        assert result.method == "regex"
        intent = result.payload["trade_intent"]
        assert intent.command_kind == "cancel"
        assert intent.cancel_order_class == "buy"

    def test_cancel_stop_sell(self, classifier):
        result = classifier.classify("cancel stop sell MSFT")
        assert result.intent_type == "cancel"
        assert result.payload["trade_intent"].cancel_order_class == "stop_sell"

    def test_buy_and_trigger_strategy(self, classifier):
        result = classifier.classify("buy NVDA and trigger strategy")
        intent = result.payload["trade_intent"]
        assert intent.trigger_strategy is True
        assert intent.execution_mode == "strategy"

    def test_greeting_prefixed_buy_still_classifies_as_trade(self, classifier):
        result = classifier.classify("hello buy 3 shares of apple")
        assert result.intent_type == "trade_command"
        assert result.payload["trade_intent"].action == "BUY"

    def test_greeting_prefixed_cancel_still_classifies_as_cancel(self, classifier):
        result = classifier.classify("hello cancel Microsoft order")
        assert result.intent_type == "cancel"
        assert result.payload["trade_intent"].command_kind == "cancel"

    def test_markdown_prefixed_strategy_trade_still_classifies(self, classifier):
        result = classifier.classify("* buy £2000 MSFT and trigger strategy")
        assert result.intent_type == "trade_command"
        assert result.payload["trade_intent"].trigger_strategy is True


# ---------------------------------------------------------------------------
# Layer 1 — Regex: Stop-loss updates (subject / price extraction)
# ---------------------------------------------------------------------------


class TestStopUpdates:
    @pytest.mark.parametrize(
        "message,subject,stop_price",
        [
            ("set stop for AAPL to $150", "AAPL", 150.0),
            ("update stop-loss for TSLA to 250.50", "TSLA", 250.50),
            ("move stop on MSFT to $380", "MSFT", None),
            ("raise stop for GOOG to $175", "GOOG", None),
        ],
    )
    def test_stop_update_extraction(self, classifier, message, subject, stop_price):
        result = classifier.classify(message)
        assert result.intent_type == "update_stop"
        assert result.payload["subject"] == subject
        if stop_price is not None:
            assert result.payload["stop_price"] == stop_price


# ---------------------------------------------------------------------------
# Layer 1 — Regex: Portfolio rules (rule / bucket / threshold extraction)
# ---------------------------------------------------------------------------


class TestPortfolioRules:
    @pytest.mark.parametrize(
        "message,rule,bucket,threshold",
        [
            ("liquidate all holdings below £100", "value_below", None, 100.0),
            ("sell all positions under $200", "value_below", None, 200.0),
            # threshold auto-negated for losers
            ("liquidate all losers below 5%", "pnl_threshold", "losers", -5.0),
            ("sell all winners above 20%", "pnl_threshold", "winners", 20.0),
        ],
    )
    def test_portfolio_rule_extraction(
        self, classifier, message, rule, bucket, threshold
    ):
        result = classifier.classify(message)
        assert result.intent_type == "portfolio_rule"
        assert result.payload["rule"] == rule
        assert result.payload["threshold"] == threshold
        if bucket is not None:
            assert result.payload["bucket"] == bucket


# ---------------------------------------------------------------------------
# Layer 1 — Regex: Compare requests (structured subjects / post-compare trade)
# ---------------------------------------------------------------------------


class TestCompareRequests:
    def test_compare_two_tickers(self, classifier):
        result = classifier.classify("compare NVDA and AMD")
        assert result.intent_type == "compare"
        compare = result.payload["compare_request"]
        assert "NVDA" in compare.subjects
        assert "AMD" in compare.subjects

    def test_compare_then_buy_stronger(self, classifier):
        result = classifier.classify("compare NVDA and AMD then buy the stronger one")
        assert result.intent_type == "compare"
        assert result.payload["compare_request"].post_compare_trade_intent is not None


# ---------------------------------------------------------------------------
# Layer 2 — Heuristic: research follow-up context
# ---------------------------------------------------------------------------


class TestResearchContext:
    def test_follow_up_with_context(self, classifier):
        context = {"last_subject_tickers": ["AAPL_US_EQ"]}
        result = classifier.classify("tell me more", context)
        assert result.intent_type == "research"
        assert result.payload.get("follow_up") is True
        assert result.payload["context_tickers"] == ["AAPL_US_EQ"]

    def test_that_one_with_context(self, classifier):
        context = {"last_subject_tickers": ["NVDA_US_EQ"]}
        result = classifier.classify("dig deeper on that one", context)
        assert result.intent_type == "research"

    def test_follow_up_without_context_falls_to_ambiguous(self, classifier):
        # No context tickers and "tell me more" alone doesn't match RESEARCH_HINT_RE
        result = classifier.classify("tell me more", {})
        assert result.intent_type == "ambiguous"


# ---------------------------------------------------------------------------
# ClassifiedIntent properties
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,is_deterministic,is_actionable",
    [
        ("buy AAPL", True, True),      # regex trade command
        ("hello", True, False),         # heuristic greeting
        ("the weather is nice", None, False),  # ambiguous (determinism not asserted)
    ],
)
def test_classified_intent_properties(
    classifier, message, is_deterministic, is_actionable
):
    result = classifier.classify(message)
    if is_deterministic is not None:
        assert result.is_deterministic is is_deterministic
    assert result.is_actionable is is_actionable


# ---------------------------------------------------------------------------
# Trade mode override in heuristic layer
# ---------------------------------------------------------------------------


def test_trade_mode_with_non_command_text(classifier):
    result = classifier.classify(
        "I want to invest in semiconductors", {}, requested_mode="trade"
    )
    assert result.intent_type == "trade_command"
    assert result.payload.get("inferred_from_mode") is True
    assert result.confidence < 0.75  # Lower confidence for inferred
