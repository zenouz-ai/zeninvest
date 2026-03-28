"""Tests for the deterministic IntentClassifier.

Tests cover all three layers:
  Layer 1 — Regex: trade commands, stop updates, portfolio rules, confirm/reject
  Layer 2 — Heuristic: greetings, help, compare, research, follow-up context
  Layer 3 — Ambiguous fallback
"""

import os
import sys

os.environ.setdefault("INVESTMENT_AGENT_USE_INMEMORY_DB", "1")

import pytest

from src.agents.conversation.intent_classifier import ClassifiedIntent, IntentClassifier


@pytest.fixture
def classifier():
    return IntentClassifier()


# ---------------------------------------------------------------------------
# Layer 1 — Regex: Confirm / Reject
# ---------------------------------------------------------------------------


class TestConfirmReject:
    def test_yes_classified_as_confirm(self, classifier):
        result = classifier.classify("yes")
        assert result.intent_type == "confirm"
        assert result.confidence >= 0.95
        assert result.method == "regex"

    def test_confirm_word_classified_as_confirm(self, classifier):
        result = classifier.classify("confirm")
        assert result.intent_type == "confirm"

    def test_go_ahead_classified_as_confirm(self, classifier):
        result = classifier.classify("go ahead")
        assert result.intent_type == "confirm"

    def test_no_classified_as_reject(self, classifier):
        result = classifier.classify("no")
        assert result.intent_type == "reject"
        assert result.confidence >= 0.95
        assert result.method == "regex"

    def test_reject_word_classified_as_reject(self, classifier):
        result = classifier.classify("reject")
        assert result.intent_type == "reject"

    def test_cancel_word_classified_as_reject(self, classifier):
        result = classifier.classify("cancel")
        assert result.intent_type == "reject"


# ---------------------------------------------------------------------------
# Layer 1 — Regex: Trade commands (BUY/SELL/REVIEW/CANCEL)
# ---------------------------------------------------------------------------


class TestTradeCommands:
    def test_buy_command(self, classifier):
        result = classifier.classify("buy AAPL")
        assert result.intent_type == "trade_command"
        assert result.confidence >= 0.90
        assert result.method == "regex"
        assert result.payload["trade_intent"].action == "BUY"

    def test_sell_command(self, classifier):
        result = classifier.classify("sell MSFT")
        assert result.intent_type == "trade_command"
        assert result.payload["trade_intent"].action == "SELL"

    def test_buy_with_amount(self, classifier):
        result = classifier.classify("buy £500 AAPL")
        assert result.intent_type == "trade_command"
        intent = result.payload["trade_intent"]
        assert intent.action == "BUY"
        assert intent.amount_gbp == 500.0

    def test_buy_with_quantity(self, classifier):
        result = classifier.classify("buy 10 shares of NVDA")
        assert result.intent_type == "trade_command"
        intent = result.payload["trade_intent"]
        assert intent.action == "BUY"
        assert intent.quantity_shares == 10.0

    def test_force_buy(self, classifier):
        result = classifier.classify("force buy AAPL")
        assert result.intent_type == "trade_command"
        assert result.payload["trade_intent"].force is True

    def test_override_buy(self, classifier):
        result = classifier.classify("override buy TSLA")
        assert result.intent_type == "trade_command"
        assert result.payload["trade_intent"].force is True

    def test_bang_buy(self, classifier):
        result = classifier.classify("!buy AMZN")
        assert result.intent_type == "trade_command"
        assert result.payload["trade_intent"].force is True

    def test_review_command(self, classifier):
        result = classifier.classify("review ASML")
        assert result.intent_type == "review"
        assert result.method == "regex"
        assert result.payload["trade_intent"].command_kind == "review"

    def test_review_and_buy(self, classifier):
        result = classifier.classify("review AAPL and buy")
        assert result.intent_type == "trade_command"
        intent = result.payload["trade_intent"]
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
        intent = result.payload["trade_intent"]
        assert intent.cancel_order_class == "stop_sell"

    def test_buy_and_trigger_strategy(self, classifier):
        result = classifier.classify("buy NVDA and trigger strategy")
        assert result.intent_type == "trade_command"
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
# Layer 1 — Regex: Stop-loss updates
# ---------------------------------------------------------------------------


class TestStopUpdates:
    def test_set_stop_for_ticker(self, classifier):
        result = classifier.classify("set stop for AAPL to $150")
        assert result.intent_type == "update_stop"
        assert result.confidence >= 0.85
        assert result.method == "regex"
        assert result.payload["subject"] == "AAPL"
        assert result.payload["stop_price"] == 150.0

    def test_update_stop_loss(self, classifier):
        result = classifier.classify("update stop-loss for TSLA to 250.50")
        assert result.intent_type == "update_stop"
        assert result.payload["stop_price"] == 250.50

    def test_move_stop(self, classifier):
        result = classifier.classify("move stop on MSFT to $380")
        assert result.intent_type == "update_stop"
        assert result.payload["subject"] == "MSFT"

    def test_raise_stop(self, classifier):
        result = classifier.classify("raise stop for GOOG to $175")
        assert result.intent_type == "update_stop"


# ---------------------------------------------------------------------------
# Layer 1 — Regex: Portfolio rules
# ---------------------------------------------------------------------------


class TestPortfolioRules:
    def test_liquidate_below_value(self, classifier):
        result = classifier.classify("liquidate all holdings below £100")
        assert result.intent_type == "portfolio_rule"
        assert result.confidence >= 0.85
        assert result.method == "regex"
        assert result.payload["rule"] == "value_below"
        assert result.payload["threshold"] == 100.0

    def test_sell_positions_under_value(self, classifier):
        result = classifier.classify("sell all positions under $200")
        assert result.intent_type == "portfolio_rule"
        assert result.payload["threshold"] == 200.0

    def test_liquidate_losers(self, classifier):
        result = classifier.classify("liquidate all losers below 5%")
        assert result.intent_type == "portfolio_rule"
        assert result.payload["rule"] == "pnl_threshold"
        assert result.payload["bucket"] == "losers"
        assert result.payload["threshold"] == -5.0  # Auto-negated for losers

    def test_liquidate_winners(self, classifier):
        result = classifier.classify("sell all winners above 20%")
        assert result.intent_type == "portfolio_rule"
        assert result.payload["bucket"] == "winners"
        assert result.payload["threshold"] == 20.0


# ---------------------------------------------------------------------------
# Layer 1 — Regex: Compare requests
# ---------------------------------------------------------------------------


class TestCompareRequests:
    def test_compare_two_tickers(self, classifier):
        result = classifier.classify("compare NVDA and AMD")
        assert result.intent_type == "compare"
        assert result.confidence >= 0.80
        assert result.method == "regex"
        compare = result.payload["compare_request"]
        assert "NVDA" in compare.subjects
        assert "AMD" in compare.subjects

    def test_compare_three_tickers(self, classifier):
        result = classifier.classify("compare AAPL, MSFT and GOOG")
        assert result.intent_type == "compare"

    def test_compare_then_buy_stronger(self, classifier):
        result = classifier.classify("compare NVDA and AMD then buy the stronger one")
        assert result.intent_type == "compare"
        compare = result.payload["compare_request"]
        assert compare.post_compare_trade_intent is not None


# ---------------------------------------------------------------------------
# Layer 2 — Heuristic: Greetings
# ---------------------------------------------------------------------------


class TestGreetings:
    def test_hello(self, classifier):
        result = classifier.classify("hello")
        assert result.intent_type == "greeting"
        assert result.method == "heuristic"
        assert result.confidence >= 0.90

    def test_hi(self, classifier):
        result = classifier.classify("hi")
        assert result.intent_type == "greeting"

    def test_thanks(self, classifier):
        result = classifier.classify("thanks")
        assert result.intent_type == "greeting"


# ---------------------------------------------------------------------------
# Layer 2 — Heuristic: Help
# ---------------------------------------------------------------------------


class TestHelp:
    def test_help_keyword(self, classifier):
        result = classifier.classify("help")
        assert result.intent_type == "help"
        assert result.method == "heuristic"

    def test_what_can_you_do(self, classifier):
        result = classifier.classify("what can you do")
        assert result.intent_type == "help"

    def test_how_does_this_work(self, classifier):
        result = classifier.classify("how does this work")
        assert result.intent_type == "help"


# ---------------------------------------------------------------------------
# Layer 2 — Heuristic: Research and context
# ---------------------------------------------------------------------------


class TestResearch:
    def test_research_keyword(self, classifier):
        result = classifier.classify("research ASML")
        # "research" is caught by RESEARCH_HINT_RE in L2 but also by trade parser as REVIEW
        # The trade parser doesn't match "research X" — only "review X"
        assert result.intent_type == "research"
        assert result.method == "heuristic"

    def test_tell_me_about(self, classifier):
        result = classifier.classify("tell me about Tesla")
        assert result.intent_type == "research"

    def test_look_into(self, classifier):
        result = classifier.classify("look into semiconductor sector")
        assert result.intent_type == "research"

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
        result = classifier.classify("tell me more", {})
        # No context tickers and "tell me more" alone doesn't match RESEARCH_HINT_RE
        assert result.intent_type == "ambiguous"


# ---------------------------------------------------------------------------
# Layer 2 — Heuristic: Compare (weak match — no structured CompareRequest)
# ---------------------------------------------------------------------------


class TestHeuristicCompare:
    def test_versus_keyword(self, classifier):
        result = classifier.classify("how does Apple versus Google look")
        # "versus" triggers compare hint in L2 (after L1 compare_request returns None)
        assert result.intent_type == "compare"
        assert result.method == "heuristic"


# ---------------------------------------------------------------------------
# Layer 2 — Heuristic: Portfolio query
# ---------------------------------------------------------------------------


class TestPortfolioQuery:
    def test_portfolio_keyword(self, classifier):
        result = classifier.classify("how's my portfolio doing")
        assert result.intent_type == "portfolio_query"
        assert result.method == "heuristic"

    def test_show_positions(self, classifier):
        result = classifier.classify("show me my positions")
        assert result.intent_type == "portfolio_query"

    def test_holdings_keyword(self, classifier):
        result = classifier.classify("what are my current holdings")
        assert result.intent_type == "portfolio_query"


# ---------------------------------------------------------------------------
# Layer 2 — Heuristic: Committee / bull-bear views
# ---------------------------------------------------------------------------


class TestCommittee:
    def test_bull_bear_views(self, classifier):
        result = classifier.classify("give me the bull and bear case for NVDA")
        assert result.intent_type == "committee"
        assert result.method == "heuristic"

    def test_risk_assessment(self, classifier):
        result = classifier.classify("what are the risk factors for ASML")
        assert result.intent_type == "committee"

    def test_pros_and_cons(self, classifier):
        result = classifier.classify("pros and cons of investing in Tesla")
        assert result.intent_type == "committee"


# ---------------------------------------------------------------------------
# Layer 2 — Heuristic: Opportunity
# ---------------------------------------------------------------------------


class TestOpportunity:
    def test_opportunities_keyword(self, classifier):
        result = classifier.classify("any interesting opportunities right now")
        assert result.intent_type == "opportunity"
        assert result.method == "heuristic"

    def test_what_should_i_buy(self, classifier):
        result = classifier.classify("what should i buy")
        assert result.intent_type == "opportunity"


# ---------------------------------------------------------------------------
# Ambiguous / fallback
# ---------------------------------------------------------------------------


class TestAmbiguous:
    def test_empty_message(self, classifier):
        result = classifier.classify("")
        assert result.intent_type == "ambiguous"
        assert result.confidence == 0.0

    def test_whitespace_only(self, classifier):
        result = classifier.classify("   ")
        assert result.intent_type == "ambiguous"

    def test_random_text(self, classifier):
        result = classifier.classify("the weather is nice today")
        assert result.intent_type == "ambiguous"
        assert result.confidence <= 0.50

    def test_none_message(self, classifier):
        result = classifier.classify(None)
        assert result.intent_type == "ambiguous"


# ---------------------------------------------------------------------------
# ClassifiedIntent properties
# ---------------------------------------------------------------------------


class TestClassifiedIntentProperties:
    def test_is_deterministic_for_regex(self, classifier):
        result = classifier.classify("buy AAPL")
        assert result.is_deterministic is True

    def test_is_deterministic_for_heuristic(self, classifier):
        result = classifier.classify("hello")
        assert result.is_deterministic is True

    def test_is_actionable_for_trade(self, classifier):
        result = classifier.classify("buy AAPL")
        assert result.is_actionable is True

    def test_is_not_actionable_for_greeting(self, classifier):
        result = classifier.classify("hello")
        assert result.is_actionable is False

    def test_is_not_actionable_for_ambiguous(self, classifier):
        result = classifier.classify("the weather is nice")
        assert result.is_actionable is False


# ---------------------------------------------------------------------------
# Trade mode override in heuristic layer
# ---------------------------------------------------------------------------


class TestModeOverride:
    def test_trade_mode_with_non_command_text(self, classifier):
        result = classifier.classify(
            "I want to invest in semiconductors",
            {},
            requested_mode="trade",
        )
        assert result.intent_type == "trade_command"
        assert result.payload.get("inferred_from_mode") is True
        assert result.confidence < 0.75  # Lower confidence for inferred


# ---------------------------------------------------------------------------
# Edge cases: priority / ordering
# ---------------------------------------------------------------------------


class TestPriorityOrdering:
    def test_buy_takes_priority_over_research_keyword(self, classifier):
        """'buy AAPL' should match trade_command, not research."""
        result = classifier.classify("buy AAPL")
        assert result.intent_type == "trade_command"
        assert result.method == "regex"

    def test_review_takes_priority_over_research_hint(self, classifier):
        """'review AAPL' should match review, not research."""
        result = classifier.classify("review AAPL")
        assert result.intent_type == "review"
        assert result.method == "regex"

    def test_compare_regex_beats_heuristic(self, classifier):
        """Structured compare request (regex L1) should beat heuristic L2."""
        result = classifier.classify("compare NVDA and AMD")
        assert result.method == "regex"
        assert result.confidence > 0.80

    def test_confirm_takes_priority_over_everything(self, classifier):
        """'yes' should be confirm even if it somehow matches other patterns."""
        result = classifier.classify("yes")
        assert result.intent_type == "confirm"

    def test_stop_update_priority_over_research(self, classifier):
        """Stop update should match before research keywords."""
        result = classifier.classify("set stop for AAPL to $150")
        assert result.intent_type == "update_stop"
        assert result.method == "regex"
