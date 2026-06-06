"""Tests for EntityResolver — pronoun, ordinal, winner/loser, portfolio scope.

Resolution cases are consolidated into context-aware tables: each row supplies
the message, SessionContext kwargs, resolve() kwargs, and the attributes it
asserts. Confirmation-prompt and audit-detail cases keep dedicated tests.
"""

import os

os.environ.setdefault("INVESTMENT_AGENT_USE_INMEMORY_DB", "1")

import pytest

from src.agents.conversation.context import SessionContext
from src.agents.conversation.resolver import EntityResolver, ResolvedEntities


@pytest.fixture
def resolver():
    return EntityResolver()


# ---------------------------------------------------------------------------
# Successful resolution across layers 1-4
# (explicit / pronoun / ordinal / winner-loser). "_min_confidence" is an
# optional floor; all other keys are exact attribute assertions.
# ---------------------------------------------------------------------------

RESOLUTION_CASES = [
    # Layer 1 — explicit tickers (override pronouns, high confidence)
    ("buy something", {}, {"explicit_tickers": ["AAPL_US_EQ"]},
     {"tickers": ["AAPL_US_EQ"], "method": "explicit", "_min_confidence": 0.90}),
    ("buy it", {"last_subject_tickers": ["MSFT_US_EQ"]}, {"explicit_tickers": ["AAPL_US_EQ"]},
     {"tickers": ["AAPL_US_EQ"], "method": "explicit"}),
    # Layer 2 — pronouns
    ("buy it", {"last_subject_tickers": ["AAPL_US_EQ"]}, {},
     {"tickers": ["AAPL_US_EQ"], "method": "pronoun", "_min_confidence": 0.80}),
    ("sell that stock", {"last_subject_tickers": ["NVDA_US_EQ"]}, {},
     {"tickers": ["NVDA_US_EQ"]}),
    ("review this one", {"last_subject_tickers": ["TSLA_US_EQ"]}, {},
     {"tickers": ["TSLA_US_EQ"]}),
    ("compare both", {"last_subject_tickers": ["AAPL_US_EQ", "MSFT_US_EQ"]}, {},
     {"tickers": ["AAPL_US_EQ", "MSFT_US_EQ"], "method": "pronoun"}),
    ("sell them", {"last_subject_tickers": ["NVDA_US_EQ", "AMD_US_EQ"]}, {},
     {"tickers": ["NVDA_US_EQ", "AMD_US_EQ"]}),
    # Layer 3 — ordinals (incl. fallback to selection tickers)
    ("buy the first one", {"last_subject_tickers": ["AAPL_US_EQ", "MSFT_US_EQ"]}, {},
     {"tickers": ["AAPL_US_EQ"], "method": "ordinal"}),
    ("sell the second one", {"last_subject_tickers": ["AAPL_US_EQ", "MSFT_US_EQ"]}, {},
     {"tickers": ["MSFT_US_EQ"], "method": "ordinal"}),
    ("buy the first one",
     {"last_subject_tickers": [], "last_selection_tickers": ["GOOG_US_EQ", "META_US_EQ"]}, {},
     {"tickers": ["GOOG_US_EQ"]}),
    # Layer 4 — winner / loser
    ("buy the winner", {"last_selection_result": {"winner": "NVDA_US_EQ", "loser": "AMD_US_EQ"}}, {},
     {"tickers": ["NVDA_US_EQ"], "method": "winner", "_min_confidence": 0.85}),
    ("buy the stronger one", {"last_selection_result": {"winner": "AAPL_US_EQ"}}, {},
     {"tickers": ["AAPL_US_EQ"]}),
    ("sell the loser", {"last_selection_result": {"winner": "NVDA_US_EQ", "loser": "AMD_US_EQ"}}, {},
     {"tickers": ["AMD_US_EQ"], "method": "loser"}),
    ("buy the best", {"last_selection_result": {"winner": "GOOG_US_EQ"}}, {},
     {"tickers": ["GOOG_US_EQ"]}),
]


@pytest.mark.parametrize("message,ctx_kwargs,resolve_kwargs,expected", RESOLUTION_CASES)
def test_resolution(resolver, message, ctx_kwargs, resolve_kwargs, expected):
    result = resolver.resolve(message, SessionContext(**ctx_kwargs), **resolve_kwargs)
    for attr, value in expected.items():
        if attr == "_min_confidence":
            assert result.confidence >= value
        else:
            assert getattr(result, attr) == value, f"{attr} mismatch for {message!r}"


# ---------------------------------------------------------------------------
# Unresolved: missing context / no references -> resolved is False
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,ctx_kwargs",
    [
        ("buy the first one", {}),                    # ordinal, no context
        ("buy the winner", {}),                       # winner, no selection result
        ("", {}),                                     # empty
        ("what is the market doing today", {}),       # no references
    ],
)
def test_unresolved(resolver, message, ctx_kwargs):
    assert resolver.resolve(message, SessionContext(**ctx_kwargs)).resolved is False


def test_it_without_context_asks_confirmation(resolver):
    result = resolver.resolve("buy it", SessionContext())
    assert result.tickers == []
    assert result.needs_confirmation is True
    assert "which stock" in result.confirmation_prompt.lower()


def test_both_without_enough_context_asks_confirmation(resolver):
    result = resolver.resolve("sell both", SessionContext(last_subject_tickers=["AAPL_US_EQ"]))
    assert result.tickers == []
    assert result.needs_confirmation is True


# ---------------------------------------------------------------------------
# Portfolio scope (Layer 5): sector / threshold extraction + confirmation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,audit_key,audit_value",
    [
        ("sell all tech stocks", "sector", "Technology"),
        ("liquidate all healthcare positions", "sector", "Healthcare"),
        ("sell everything under £200", "threshold", 200.0),
        ("liquidate everything below $500", "threshold", 500.0),
    ],
)
def test_portfolio_scope(resolver, message, audit_key, audit_value):
    result = resolver.resolve(message, SessionContext())
    assert result.method == "portfolio_scope"
    assert result.needs_confirmation is True
    assert result.audit[audit_key] == audit_value
    if audit_key == "sector":
        assert audit_value in result.confirmation_prompt


# ---------------------------------------------------------------------------
# ResolvedEntities.resolved property
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs,is_resolved",
    [
        ({"tickers": ["A"], "confidence": 0.9}, True),
        ({"tickers": [], "confidence": 0.5}, False),
        ({"tickers": [], "confidence": 0.75, "needs_confirmation": True}, True),
    ],
)
def test_resolved_property(kwargs, is_resolved):
    assert ResolvedEntities(**kwargs).resolved is is_resolved
