"""Tests for EntityResolver — pronoun, ordinal, winner/loser, portfolio scope."""

import os

os.environ.setdefault("INVESTMENT_AGENT_USE_INMEMORY_DB", "1")

import pytest

from src.agents.conversation.context import SessionContext
from src.agents.conversation.resolver import EntityResolver, ResolvedEntities


@pytest.fixture
def resolver():
    return EntityResolver()


# ---------------------------------------------------------------------------
# Explicit tickers (Layer 1)
# ---------------------------------------------------------------------------


class TestExplicitTickers:
    def test_explicit_tickers_returned_directly(self, resolver):
        ctx = SessionContext()
        result = resolver.resolve("buy something", ctx, explicit_tickers=["AAPL_US_EQ"])
        assert result.tickers == ["AAPL_US_EQ"]
        assert result.confidence >= 0.90
        assert result.method == "explicit"

    def test_explicit_tickers_override_pronouns(self, resolver):
        ctx = SessionContext(last_subject_tickers=["MSFT_US_EQ"])
        result = resolver.resolve("buy it", ctx, explicit_tickers=["AAPL_US_EQ"])
        assert result.tickers == ["AAPL_US_EQ"]
        assert result.method == "explicit"


# ---------------------------------------------------------------------------
# Pronoun resolution (Layer 2)
# ---------------------------------------------------------------------------


class TestPronounResolution:
    def test_it_resolves_to_last_subject(self, resolver):
        ctx = SessionContext(last_subject_tickers=["AAPL_US_EQ"])
        result = resolver.resolve("buy it", ctx)
        assert result.tickers == ["AAPL_US_EQ"]
        assert result.method == "pronoun"
        assert result.confidence >= 0.80

    def test_that_stock_resolves(self, resolver):
        ctx = SessionContext(last_subject_tickers=["NVDA_US_EQ"])
        result = resolver.resolve("sell that stock", ctx)
        assert result.tickers == ["NVDA_US_EQ"]

    def test_this_one_resolves(self, resolver):
        ctx = SessionContext(last_subject_tickers=["TSLA_US_EQ"])
        result = resolver.resolve("review this one", ctx)
        assert result.tickers == ["TSLA_US_EQ"]

    def test_it_without_context_asks_confirmation(self, resolver):
        ctx = SessionContext()
        result = resolver.resolve("buy it", ctx)
        assert result.tickers == []
        assert result.needs_confirmation is True
        assert "which stock" in result.confirmation_prompt.lower()

    def test_both_resolves_to_two(self, resolver):
        ctx = SessionContext(last_subject_tickers=["AAPL_US_EQ", "MSFT_US_EQ"])
        result = resolver.resolve("compare both", ctx)
        assert result.tickers == ["AAPL_US_EQ", "MSFT_US_EQ"]
        assert result.method == "pronoun"

    def test_them_resolves_to_two(self, resolver):
        ctx = SessionContext(last_subject_tickers=["NVDA_US_EQ", "AMD_US_EQ"])
        result = resolver.resolve("sell them", ctx)
        assert result.tickers == ["NVDA_US_EQ", "AMD_US_EQ"]

    def test_both_without_enough_context(self, resolver):
        ctx = SessionContext(last_subject_tickers=["AAPL_US_EQ"])
        result = resolver.resolve("sell both", ctx)
        assert result.tickers == []
        assert result.needs_confirmation is True


# ---------------------------------------------------------------------------
# Ordinal resolution (Layer 3)
# ---------------------------------------------------------------------------


class TestOrdinalResolution:
    def test_first_one(self, resolver):
        ctx = SessionContext(last_subject_tickers=["AAPL_US_EQ", "MSFT_US_EQ"])
        result = resolver.resolve("buy the first one", ctx)
        assert result.tickers == ["AAPL_US_EQ"]
        assert result.method == "ordinal"

    def test_second_one(self, resolver):
        ctx = SessionContext(last_subject_tickers=["AAPL_US_EQ", "MSFT_US_EQ"])
        result = resolver.resolve("sell the second one", ctx)
        assert result.tickers == ["MSFT_US_EQ"]
        assert result.method == "ordinal"

    def test_first_without_context_unresolved(self, resolver):
        ctx = SessionContext()
        result = resolver.resolve("buy the first one", ctx)
        assert result.resolved is False

    def test_ordinal_falls_back_to_selection_tickers(self, resolver):
        ctx = SessionContext(
            last_subject_tickers=[],
            last_selection_tickers=["GOOG_US_EQ", "META_US_EQ"],
        )
        result = resolver.resolve("buy the first one", ctx)
        assert result.tickers == ["GOOG_US_EQ"]


# ---------------------------------------------------------------------------
# Winner / loser resolution (Layer 4)
# ---------------------------------------------------------------------------


class TestWinnerLoserResolution:
    def test_the_winner(self, resolver):
        ctx = SessionContext(last_selection_result={"winner": "NVDA_US_EQ", "loser": "AMD_US_EQ"})
        result = resolver.resolve("buy the winner", ctx)
        assert result.tickers == ["NVDA_US_EQ"]
        assert result.method == "winner"
        assert result.confidence >= 0.85

    def test_the_stronger_one(self, resolver):
        ctx = SessionContext(last_selection_result={"winner": "AAPL_US_EQ"})
        result = resolver.resolve("buy the stronger one", ctx)
        assert result.tickers == ["AAPL_US_EQ"]

    def test_the_loser(self, resolver):
        ctx = SessionContext(last_selection_result={"winner": "NVDA_US_EQ", "loser": "AMD_US_EQ"})
        result = resolver.resolve("sell the loser", ctx)
        assert result.tickers == ["AMD_US_EQ"]
        assert result.method == "loser"

    def test_winner_without_selection_result(self, resolver):
        ctx = SessionContext()
        result = resolver.resolve("buy the winner", ctx)
        assert result.resolved is False

    def test_the_best(self, resolver):
        ctx = SessionContext(last_selection_result={"winner": "GOOG_US_EQ"})
        result = resolver.resolve("buy the best", ctx)
        assert result.tickers == ["GOOG_US_EQ"]


# ---------------------------------------------------------------------------
# Portfolio scope (Layer 5)
# ---------------------------------------------------------------------------


class TestPortfolioScope:
    def test_all_tech_stocks(self, resolver):
        ctx = SessionContext()
        result = resolver.resolve("sell all tech stocks", ctx)
        assert result.method == "portfolio_scope"
        assert result.needs_confirmation is True
        assert "Technology" in result.confirmation_prompt
        assert result.audit["sector"] == "Technology"

    def test_all_healthcare_positions(self, resolver):
        ctx = SessionContext()
        result = resolver.resolve("liquidate all healthcare positions", ctx)
        assert result.audit["sector"] == "Healthcare"

    def test_everything_under_200(self, resolver):
        ctx = SessionContext()
        result = resolver.resolve("sell everything under £200", ctx)
        assert result.method == "portfolio_scope"
        assert result.needs_confirmation is True
        assert result.audit["threshold"] == 200.0

    def test_everything_below_500(self, resolver):
        ctx = SessionContext()
        result = resolver.resolve("liquidate everything below $500", ctx)
        assert result.audit["threshold"] == 500.0


# ---------------------------------------------------------------------------
# No resolution
# ---------------------------------------------------------------------------


class TestNoResolution:
    def test_empty_message(self, resolver):
        ctx = SessionContext()
        result = resolver.resolve("", ctx)
        assert result.resolved is False

    def test_no_references(self, resolver):
        ctx = SessionContext()
        result = resolver.resolve("what is the market doing today", ctx)
        assert result.resolved is False

    def test_resolved_property(self, resolver):
        r = ResolvedEntities(tickers=["A"], confidence=0.9)
        assert r.resolved is True

    def test_not_resolved_empty_tickers_no_confirmation(self, resolver):
        r = ResolvedEntities(tickers=[], confidence=0.5)
        assert r.resolved is False

    def test_resolved_with_needs_confirmation(self, resolver):
        r = ResolvedEntities(tickers=[], confidence=0.75, needs_confirmation=True)
        assert r.resolved is True
