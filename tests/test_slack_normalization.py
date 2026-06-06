"""Slack message normalization and edge-case tests (Phase 6).

Exercises the public ``parse_trade_command`` entry (normalization + force-prefix
handling), which is a different code path from the raw regex tested in
test_trade_command_parser.py. Slack-formatting variants are consolidated into a
robustness table; attribute extraction and empty inputs into parametrized tables.
"""

import os

os.environ.setdefault("INVESTMENT_AGENT_USE_INMEMORY_DB", "1")

import pytest

from src.agents.notifications.trade_command_parser import parse_trade_command


# ---------------------------------------------------------------------------
# Slack-formatting robustness: parsing must not raise; if a command is
# recognized, the action is correct. Documents tolerated input variants
# (bullets, numbered/dash lists, unicode, smart quotes, NBSP, zero-width,
# bold/code markdown, and very long messages — no catastrophic backtracking).
# Non-printing characters use escape sequences for source readability.
# ---------------------------------------------------------------------------

NORMALIZATION_CASES = [
    ("• buy AAPL", "BUY"),             # bullet
    ("1. buy AAPL", "BUY"),                 # numbered list
    ("- buy MSFT", "BUY"),                  # dash list
    ("buy AAPL — 500", "BUY"),         # em dash
    ("buy “AAPL”", "BUY"),        # smart/curly quotes
    ("buy\xa0AAPL", "BUY"),                 # non-breaking space
    ("buy\u200bAAPL", "BUY"),               # zero-width space
    ("*buy* AAPL", "BUY"),                  # bold markdown
    ("buy `AAPL`", "BUY"),                  # code span
    ("buy AAPL " + "x" * 5000, "BUY"),      # length / ReDoS guard
]


@pytest.mark.parametrize("message,action", NORMALIZATION_CASES)
def test_slack_formatting_is_robust(message, action):
    result = parse_trade_command(message, use_llm_fallback=False)
    if result is not None:
        assert result.action == action


def test_user_mention_not_parsed_as_ticker():
    result = parse_trade_command("<@U12345> buy AAPL", use_llm_fallback=False)
    if result is not None:
        assert result.action == "BUY"
        assert "<@U12345>" not in (result.ticker or "")


# ---------------------------------------------------------------------------
# Attribute extraction via the public entry: force prefixes, amounts/quantities,
# review/cancel kinds, and case-insensitivity.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,expected",
    [
        ("force buy AAPL", {"action": "BUY", "force": True}),
        ("override buy TSLA", {"force": True}),
        ("!buy AMZN", {"force": True}),
        ("force sell MSFT", {"action": "SELL", "force": True}),
        ("!sell GOOG", {"action": "SELL", "force": True}),
        ("buy £500 AAPL", {"amount_gbp": 500.0}),
        ("buy $1000 MSFT", {"amount_gbp": 1000.0}),
        ("buy 10 shares of NVDA", {"quantity_shares": 10.0}),
        ("buy 2.5 shares of TSLA", {"quantity_shares": 2.5}),
        ("review ASML", {"command_kind": "review"}),
        ("review AAPL and buy", {"action": "BUY", "trigger_strategy": True}),
        ("cancel buy AAPL", {"command_kind": "cancel", "cancel_order_class": "buy"}),
        ("cancel stop sell MSFT", {"cancel_order_class": "stop_sell"}),
        ("BUY AAPL", {"action": "BUY"}),
        ("Buy aapl", {"action": "BUY"}),
    ],
)
def test_parse_command_attributes(message, expected):
    result = parse_trade_command(message, use_llm_fallback=False)
    assert result is not None
    for attr, value in expected.items():
        assert getattr(result, attr) == value, f"{attr} mismatch for {message!r}"


@pytest.mark.parametrize("message", ["", "   ", None])
def test_parse_empty_returns_none(message):
    assert parse_trade_command(message, use_llm_fallback=False) is None
