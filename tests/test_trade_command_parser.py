"""Tests for natural language trade command parser (US-1.6)."""

import pytest

from src.agents.notifications.trade_command_parser import (
    TradeCommandIntent,
    _strip_force_prefix,
    _try_regex,
    parse_trade_command,
)
from src.data.models import IntentDetectionCache


class TestRegexParser:
    """Test regex-based parsing (zero-cost path)."""

    def test_buy_ticker(self):
        result = _try_regex("BUY AAPL")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "AAPL"
        assert result.execution_mode == "direct"
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
        assert result.command_kind == "review"
        assert result.execution_mode == "strategy"

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

    def test_company_name_buy_apple(self):
        result = _try_regex("buy apple")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "APPLE"

    def test_company_name_sell_google(self):
        result = _try_regex("sell google")
        assert result is not None
        assert result.action == "SELL"
        assert result.ticker == "GOOGLE"

    def test_company_name_review_nvidia(self):
        result = _try_regex("review nvidia")
        assert result is not None
        assert result.action == "REVIEW"
        assert result.ticker == "NVIDIA"

    def test_company_name_with_amount(self):
        result = _try_regex("buy £500 apple")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "APPLE"
        assert result.amount_gbp == 500.0

    def test_multi_word_not_matched(self):
        result = _try_regex("buy bank of america")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "BANK OF AMERICA"
        assert result.subject_phrases == ["bank of america"]

    def test_force_buy_ticker(self):
        result = _try_regex("force buy AAPL")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "AAPL"
        assert result.force is True

    def test_force_sell_ticker(self):
        result = _try_regex("FORCE SELL TSLA")
        assert result is not None
        assert result.action == "SELL"
        assert result.ticker == "TSLA"
        assert result.force is True

    def test_override_buy(self):
        result = _try_regex("override buy MSFT")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "MSFT"
        assert result.force is True

    def test_bang_prefix_buy(self):
        result = _try_regex("!buy NVDA")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "NVDA"
        assert result.force is True

    def test_force_buy_with_quantity(self):
        result = _try_regex("force buy 5 shares of AAPL")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "AAPL"
        assert result.quantity_shares == 5.0
        assert result.force is True

    def test_force_buy_with_amount(self):
        result = _try_regex("force buy £500 MSFT")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "MSFT"
        assert result.amount_gbp == 500.0
        assert result.force is True

    def test_normal_buy_not_forced(self):
        result = _try_regex("BUY AAPL")
        assert result is not None
        assert result.force is False

    def test_force_company_name(self):
        result = _try_regex("force buy microsoft")
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "MICROSOFT"
        assert result.force is True

    def test_strategy_trigger_phrase(self):
        result = _try_regex("buy Apple and trigger strategy")
        assert result is not None
        assert result.action == "BUY"
        assert result.execution_mode == "strategy"
        assert result.trigger_strategy is True
        assert result.subject_phrases == ["Apple"]

    def test_review_and_buy_phrase(self):
        result = _try_regex("review Apple and buy")
        assert result is not None
        assert result.action == "BUY"
        assert result.command_kind == "trade"
        assert result.execution_mode == "strategy"
        assert result.trigger_strategy is True

    def test_cancel_buy_single_ticker(self):
        result = _try_regex("cancel buy Apple")
        assert result is not None
        assert result.action == "CANCEL"
        assert result.command_kind == "cancel"
        assert result.execution_mode == "cancel_only"
        assert result.cancel_order_class == "buy"
        assert result.subject_phrases == ["Apple"]

    def test_cancel_stop_sell_multi_ticker(self):
        result = _try_regex("cancel stop sell Nvidia, Microsoft and Apple")
        assert result is not None
        assert result.action == "CANCEL"
        assert result.cancel_order_class == "stop_sell"
        assert result.subject_phrases == ["Nvidia", "Microsoft", "Apple"]

    def test_cancel_without_order_class(self):
        result = _try_regex("cancel apple")
        assert result is not None
        assert result.action == "CANCEL"
        assert result.cancel_order_class == "any"
        assert result.subject_phrases == ["apple"]

    def test_greeting_prefix_buy(self):
        result = _try_regex("hello buy 3 shares of apple")
        assert result is not None
        assert result.action == "BUY"
        assert result.quantity_shares == 3.0
        assert result.subject_phrases == ["apple"]

    def test_greeting_prefix_cancel_subject_first(self):
        result = _try_regex("hello cancel Microsoft order")
        assert result is not None
        assert result.action == "CANCEL"
        assert result.cancel_order_class == "any"
        assert result.subject_phrases == ["Microsoft"]

    def test_markdown_prefix_strategy_trade(self):
        result = _try_regex("* buy £2000 MSFT and trigger strategy")
        assert result is not None
        assert result.action == "BUY"
        assert result.amount_gbp == 2000.0
        assert result.execution_mode == "strategy"
        assert result.trigger_strategy is True


class TestStripForcePrefix:
    """Test force/override/! prefix detection."""

    def test_force_prefix(self):
        cleaned, is_force = _strip_force_prefix("force buy AAPL")
        assert cleaned == "buy AAPL"
        assert is_force is True

    def test_override_prefix(self):
        cleaned, is_force = _strip_force_prefix("override SELL TSLA")
        assert cleaned == "SELL TSLA"
        assert is_force is True

    def test_bang_prefix(self):
        cleaned, is_force = _strip_force_prefix("!BUY NVDA")
        assert cleaned == "BUY NVDA"
        assert is_force is True

    def test_no_prefix(self):
        cleaned, is_force = _strip_force_prefix("BUY AAPL")
        assert cleaned == "BUY AAPL"
        assert is_force is False

    def test_force_case_insensitive(self):
        cleaned, is_force = _strip_force_prefix("FORCE BUY AAPL")
        assert cleaned == "BUY AAPL"
        assert is_force is True

    def test_force_with_leading_whitespace(self):
        cleaned, is_force = _strip_force_prefix("  force buy AAPL")
        assert cleaned == "buy AAPL"
        assert is_force is True


class TestParseTradeCommand:
    """Test the main parse_trade_command function (no LLM)."""

    def test_simple_buy(self):
        result = parse_trade_command("BUY AAPL", use_llm_fallback=False)
        assert result is not None
        assert result.action == "BUY"
        assert result.ticker == "AAPL"
        assert result.execution_mode == "direct"
        assert result.raw_message == "BUY AAPL"

    def test_empty_returns_none(self):
        assert parse_trade_command("", use_llm_fallback=False) is None
        assert parse_trade_command(None, use_llm_fallback=False) is None

    def test_non_command_returns_none(self):
        assert parse_trade_command("Good morning", use_llm_fallback=False) is None

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

    def test_to_json(self):
        intent = TradeCommandIntent(
            action="BUY", ticker="AAPL", quantity_shares=10, raw_message="BUY 10 AAPL"
        )
        json_str = intent.to_json()
        assert '"action": "BUY"' in json_str
        assert '"ticker": "AAPL"' in json_str
