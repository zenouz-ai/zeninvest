"""Tests for natural language trade command parser (US-1.6)."""

import pytest

from src.agents.notifications.trade_command_parser import (
    TradeCommandIntent,
    _try_regex,
    parse_trade_command,
)


class TestRegexParser:
    """Test regex-based parsing (zero-cost path)."""

    def test_buy_ticker(self):
        result = _try_regex("BUY AAPL")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "AAPL"
        assert result.quantity_shares is None
        assert result.amount_gbp is None

    def test_sell_ticker(self):
        result = _try_regex("SELL TSLA")
        assert result is not None
        assert result.action == "SELL"
        assert result.ticker == "TSLA"

    def test_review_ticker(self):
        result = _try_regex("REVIEW MSFT")
        assert result is not None
        assert result.action == "REVIEW"
        assert result.ticker == "MSFT"

    def test_buy_with_quantity(self):
        result = _try_regex("BUY 10 AAPL")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "AAPL"
        assert result.quantity_shares == 10.0

    def test_buy_shares_of(self):
        result = _try_regex("BUY 5 shares of NVDA")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "NVDA"
        assert result.quantity_shares == 5.0

    def test_buy_gbp_amount(self):
        result = _try_regex("BUY £500 MSFT")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "MSFT"
        assert result.amount_gbp == 500.0

    def test_buy_dollar_amount(self):
        result = _try_regex("BUY $1000 GOOG")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "GOOG"
        assert result.amount_gbp == 1000.0

    def test_case_insensitive(self):
        result = _try_regex("buy aapl")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "AAPL"

    def test_ticker_after_amount(self):
        result = _try_regex("BUY AAPL £500")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "AAPL"
        assert result.amount_gbp == 500.0

    def test_ticker_after_qty(self):
        result = _try_regex("SELL TSLA 15")
        assert result is not None
        assert result.action == "SELL"
        assert result.ticker == "TSLA"
        assert result.quantity_shares == 15.0

    def test_unparseable_returns_none(self):
        assert _try_regex("Hello there") is None
        assert _try_regex("What is the weather?") is None
        assert _try_regex("") is None

    def test_whitespace_handling(self):
        result = _try_regex("  BUY  AAPL  ")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "AAPL"


class TestParseTradeCommand:
    """Test the main parse_trade_command function (no LLM)."""

    def test_simple_buy(self):
        result = parse_trade_command("BUY AAPL", use_llm_fallback=False)
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "AAPL"
        assert result.raw_message == "BUY AAPL"

    def test_empty_returns_none(self):
        assert parse_trade_command("", use_llm_fallback=False) is None
        assert parse_trade_command(None, use_llm_fallback=False) is None

    def test_non_command_returns_none(self):
        assert parse_trade_command("Good morning", use_llm_fallback=False) is None

    def test_to_json(self):
        intent = TradeCommandIntent(
            action="BUY", ticker="AAPL", quantity_shares=10, raw_message="BUY 10 AAPL"
        )
        json_str = intent.to_json()
        assert '"action": "BUY"' in json_str
        assert '"ticker": "AAPL"' in json_str
