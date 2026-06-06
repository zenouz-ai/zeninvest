"""Tests for natural language trade command parser (US-1.6).

Regex-parser cases are consolidated into a table (REGEX_CASES): each row is a
message plus the exact attributes the case asserts. Richer cases (LLM-fallback
caching, JSON serialization) keep dedicated tests below.
"""

import pytest

from src.agents.notifications.trade_command_parser import (
    TradeCommandIntent,
    _strip_force_prefix,
    _try_regex,
    parse_trade_command,
)
from src.data.models import IntentDetectionCache


# ---------------------------------------------------------------------------
# Regex parser (zero-cost path): message -> asserted attributes
# ---------------------------------------------------------------------------

REGEX_CASES = [
    # basic actions / tickers (BUY AAPL also asserts it is not force-flagged)
    ("BUY AAPL", {"action": "BUY", "ticker": "AAPL", "execution_mode": "direct",
                  "quantity_shares": None, "amount_gbp": None, "force": False}),
    ("SELL TSLA", {"action": "SELL", "ticker": "TSLA"}),
    ("REVIEW MSFT", {"action": "REVIEW", "ticker": "MSFT",
                     "command_kind": "review", "execution_mode": "strategy"}),
    # quantity / amount extraction
    ("BUY 10 AAPL", {"action": "BUY", "ticker": "AAPL", "quantity_shares": 10.0}),
    ("BUY 5 shares of NVDA", {"action": "BUY", "ticker": "NVDA", "quantity_shares": 5.0}),
    ("BUY £500 MSFT", {"action": "BUY", "ticker": "MSFT", "amount_gbp": 500.0}),
    ("BUY $1000 GOOG", {"action": "BUY", "ticker": "GOOG", "amount_gbp": 1000.0}),
    ("BUY AAPL £500", {"action": "BUY", "ticker": "AAPL", "amount_gbp": 500.0}),
    ("SELL TSLA 15", {"action": "SELL", "ticker": "TSLA", "quantity_shares": 15.0}),
    # casing / whitespace
    ("buy aapl", {"action": "BUY", "ticker": "AAPL"}),
    ("  BUY  AAPL  ", {"action": "BUY", "ticker": "AAPL"}),
    # company-name tickers
    ("buy apple", {"action": "BUY", "ticker": "APPLE"}),
    ("sell google", {"action": "SELL", "ticker": "GOOGLE"}),
    ("review nvidia", {"action": "REVIEW", "ticker": "NVIDIA"}),
    ("buy £500 apple", {"action": "BUY", "ticker": "APPLE", "amount_gbp": 500.0}),
    ("buy bank of america", {"action": "BUY", "ticker": "BANK OF AMERICA",
                             "subject_phrases": ["bank of america"]}),
    # force / override / bang prefixes
    ("force buy AAPL", {"action": "BUY", "ticker": "AAPL", "force": True}),
    ("FORCE SELL TSLA", {"action": "SELL", "ticker": "TSLA", "force": True}),
    ("override buy MSFT", {"action": "BUY", "ticker": "MSFT", "force": True}),
    ("!buy NVDA", {"action": "BUY", "ticker": "NVDA", "force": True}),
    ("force buy 5 shares of AAPL", {"action": "BUY", "ticker": "AAPL",
                                    "quantity_shares": 5.0, "force": True}),
    ("force buy £500 MSFT", {"action": "BUY", "ticker": "MSFT",
                             "amount_gbp": 500.0, "force": True}),
    ("force buy microsoft", {"action": "BUY", "ticker": "MICROSOFT", "force": True}),
    # strategy-trigger phrases
    ("buy Apple and trigger strategy", {"action": "BUY", "execution_mode": "strategy",
                                        "trigger_strategy": True, "subject_phrases": ["Apple"]}),
    ("review Apple and buy", {"action": "BUY", "command_kind": "trade",
                              "execution_mode": "strategy", "trigger_strategy": True}),
    # cancel commands
    ("cancel buy Apple", {"action": "CANCEL", "command_kind": "cancel",
                          "execution_mode": "cancel_only", "cancel_order_class": "buy",
                          "subject_phrases": ["Apple"]}),
    ("cancel stop sell Nvidia, Microsoft and Apple",
     {"action": "CANCEL", "cancel_order_class": "stop_sell",
      "subject_phrases": ["Nvidia", "Microsoft", "Apple"]}),
    ("cancel apple", {"action": "CANCEL", "cancel_order_class": "any",
                      "subject_phrases": ["apple"]}),
    # greeting / markdown prefixes
    ("hello buy 3 shares of apple", {"action": "BUY", "quantity_shares": 3.0,
                                     "subject_phrases": ["apple"]}),
    ("hello cancel Microsoft order", {"action": "CANCEL", "cancel_order_class": "any",
                                      "subject_phrases": ["Microsoft"]}),
    ("* buy £2000 MSFT and trigger strategy",
     {"action": "BUY", "amount_gbp": 2000.0, "execution_mode": "strategy",
      "trigger_strategy": True}),
]


@pytest.mark.parametrize("message,expected", REGEX_CASES)
def test_regex_parse(message, expected):
    result = _try_regex(message)
    assert result is not None
    for attr, value in expected.items():
        assert getattr(result, attr) == value, f"{attr} mismatch for {message!r}"


@pytest.mark.parametrize("message", ["Hello there", "What is the weather?", ""])
def test_regex_unparseable_returns_none(message):
    assert _try_regex(message) is None


# ---------------------------------------------------------------------------
# Force/override/! prefix stripping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,cleaned,is_force",
    [
        ("force buy AAPL", "buy AAPL", True),
        ("override SELL TSLA", "SELL TSLA", True),
        ("!BUY NVDA", "BUY NVDA", True),
        ("BUY AAPL", "BUY AAPL", False),
        ("FORCE BUY AAPL", "BUY AAPL", True),
        ("  force buy AAPL", "buy AAPL", True),
    ],
)
def test_strip_force_prefix(message, cleaned, is_force):
    assert _strip_force_prefix(message) == (cleaned, is_force)


# ---------------------------------------------------------------------------
# parse_trade_command (no LLM) — simple paths
# ---------------------------------------------------------------------------


def test_parse_simple_buy():
    result = parse_trade_command("BUY AAPL", use_llm_fallback=False)
    assert result is not None
    assert result.action == "BUY"
    assert result.ticker == "AAPL"
    assert result.execution_mode == "direct"
    assert result.raw_message == "BUY AAPL"


@pytest.mark.parametrize("message", ["", None, "Good morning"])
def test_parse_non_command_returns_none(message):
    assert parse_trade_command(message, use_llm_fallback=False) is None


def test_to_json():
    intent = TradeCommandIntent(
        action="BUY", ticker="AAPL", quantity_shares=10, raw_message="BUY 10 AAPL"
    )
    json_str = intent.to_json()
    assert '"action": "BUY"' in json_str
    assert '"ticker": "AAPL"' in json_str


# ---------------------------------------------------------------------------
# parse_trade_command — LLM fallback caching (integration)
# ---------------------------------------------------------------------------


class TestParseTradeCommandLLMCache:
    def test_llm_fallback_result_is_cached(
        self,
        orchestrator_db_session,
        orchestrator_session_factory,
        monkeypatch,
    ):
        calls: list[str] = []

        def fake_try_claude(message: str) -> TradeCommandIntent:
            calls.append(message)
            return TradeCommandIntent(
                action="BUY",
                ticker="APPLE",
                raw_message=message,
                command_kind="trade",
                execution_mode="direct",
                subject_phrases=["apple"],
            )

        monkeypatch.setattr(
            "src.agents.notifications.trade_command_parser._try_claude",
            fake_try_claude,
        )
        monkeypatch.setattr(
            "src.agents.notifications.trade_command_parser.get_session",
            orchestrator_session_factory,
        )

        first = parse_trade_command("please purchase apple", use_llm_fallback=True)
        second = parse_trade_command("please purchase apple", use_llm_fallback=True)

        assert first is not None
        assert second is not None
        assert len(calls) == 1

        row = orchestrator_db_session.query(IntentDetectionCache).one()
        assert row.normalized_message == "purchase apple"
        assert row.intent_kind == "trade"
        assert row.hit_count == 2

    def test_cached_llm_result_respects_no_fallback_flag(
        self,
        orchestrator_db_session,
        orchestrator_session_factory,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "src.agents.notifications.trade_command_parser._try_claude",
            lambda message: TradeCommandIntent(
                action="CANCEL",
                ticker="MICROSOFT",
                raw_message=message,
                command_kind="cancel",
                execution_mode="cancel_only",
                cancel_order_class="any",
                subject_phrases=["Microsoft"],
            ),
        )
        monkeypatch.setattr(
            "src.agents.notifications.trade_command_parser.get_session",
            orchestrator_session_factory,
        )

        assert parse_trade_command("please remove microsoft order", use_llm_fallback=True) is not None

        cached = orchestrator_db_session.query(IntentDetectionCache).one()
        assert cached.intent_kind == "cancel"
        assert parse_trade_command("please remove microsoft order", use_llm_fallback=False) is None
