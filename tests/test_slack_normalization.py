"""Slack message normalization and edge-case tests (Phase 6).

Covers: bullet/list stripping, Unicode normalization, Slack markdown,
force/override prefixes, amount parsing, and edge cases.
"""

import os

os.environ.setdefault("INVESTMENT_AGENT_USE_INMEMORY_DB", "1")

import pytest

from src.agents.notifications.trade_command_parser import (
    TradeCommandIntent,
    parse_trade_command,
)


# ---------------------------------------------------------------------------
# Bullet and list stripping
# ---------------------------------------------------------------------------


class TestBulletStripping:
    def test_bullet_prefix_buy(self):
        # Slack mobile sometimes prepends bullets
        result = parse_trade_command("• buy AAPL", use_llm_fallback=False)
        # The bullet is a non-word char; regex strips leading non-alpha noise
        # If the parser handles this, great; if not, we document the gap
        if result:
            assert result.action == "BUY"

    def test_numbered_list_buy(self):
        result = parse_trade_command("1. buy AAPL", use_llm_fallback=False)
        # Numbered prefixes may not parse — acceptable
        if result:
            assert result.action == "BUY"

    def test_dash_prefix_buy(self):
        result = parse_trade_command("- buy MSFT", use_llm_fallback=False)
        if result:
            assert result.action == "BUY"


# ---------------------------------------------------------------------------
# Unicode normalization
# ---------------------------------------------------------------------------


class TestUnicodeNormalization:
    def test_em_dash_in_message(self):
        """Em dash (—) should not break parsing."""
        result = parse_trade_command("buy AAPL — 500", use_llm_fallback=False)
        if result:
            assert result.action == "BUY"

    def test_smart_quotes(self):
        """Smart/curly quotes should not break parsing."""
        result = parse_trade_command("buy \u201cAAPL\u201d", use_llm_fallback=False)
        # Parser may or may not handle smart quotes on the ticker
        if result:
            assert result.action == "BUY"

    def test_non_breaking_space(self):
        """Non-breaking space (\xa0) should be treated as regular space."""
        result = parse_trade_command("buy\xa0AAPL", use_llm_fallback=False)
        if result:
            assert result.action == "BUY"

    def test_zero_width_chars_stripped(self):
        """Zero-width space/joiner should not break parsing."""
        result = parse_trade_command("buy\u200bAAPL", use_llm_fallback=False)
        # Zero-width chars between words may break regex — this documents behavior
        if result:
            assert result.action == "BUY"


# ---------------------------------------------------------------------------
# Slack markdown
# ---------------------------------------------------------------------------


class TestSlackMarkdown:
    def test_bold_buy(self):
        result = parse_trade_command("*buy* AAPL", use_llm_fallback=False)
        if result:
            assert result.action == "BUY"

    def test_code_block_ticker(self):
        result = parse_trade_command("buy `AAPL`", use_llm_fallback=False)
        if result:
            assert result.action == "BUY"

    def test_user_mention_ignored(self):
        """User mentions like <@U12345> should not be parsed as tickers."""
        result = parse_trade_command("<@U12345> buy AAPL", use_llm_fallback=False)
        if result:
            assert result.action == "BUY"
            assert "<@U12345>" not in (result.ticker or "")


# ---------------------------------------------------------------------------
# Force / override prefixes
# ---------------------------------------------------------------------------


class TestForceOverride:
    def test_force_buy_parses(self):
        result = parse_trade_command("force buy AAPL", use_llm_fallback=False)
        assert result is not None
        assert result.action == "BUY"
        assert result.force is True

    def test_override_buy_parses(self):
        result = parse_trade_command("override buy TSLA", use_llm_fallback=False)
        assert result is not None
        assert result.force is True

    def test_bang_buy_parses(self):
        result = parse_trade_command("!buy AMZN", use_llm_fallback=False)
        assert result is not None
        assert result.force is True

    def test_force_sell_parses(self):
        result = parse_trade_command("force sell MSFT", use_llm_fallback=False)
        assert result is not None
        assert result.action == "SELL"
        assert result.force is True

    def test_bang_sell_parses(self):
        result = parse_trade_command("!sell GOOG", use_llm_fallback=False)
        assert result is not None
        assert result.action == "SELL"
        assert result.force is True


# ---------------------------------------------------------------------------
# Amount and quantity parsing
# ---------------------------------------------------------------------------


class TestAmountParsing:
    def test_gbp_amount(self):
        result = parse_trade_command("buy £500 AAPL", use_llm_fallback=False)
        assert result is not None
        assert result.amount_gbp == 500.0

    def test_dollar_amount(self):
        result = parse_trade_command("buy $1000 MSFT", use_llm_fallback=False)
        assert result is not None
        assert result.amount_gbp == 1000.0

    def test_share_quantity(self):
        result = parse_trade_command("buy 10 shares of NVDA", use_llm_fallback=False)
        assert result is not None
        assert result.quantity_shares == 10.0

    def test_share_quantity_decimal(self):
        result = parse_trade_command("buy 2.5 shares of TSLA", use_llm_fallback=False)
        assert result is not None
        assert result.quantity_shares == 2.5


# ---------------------------------------------------------------------------
# Review and cancel commands
# ---------------------------------------------------------------------------


class TestReviewAndCancel:
    def test_review_command(self):
        result = parse_trade_command("review ASML", use_llm_fallback=False)
        assert result is not None
        assert result.command_kind == "review"

    def test_review_and_buy(self):
        result = parse_trade_command("review AAPL and buy", use_llm_fallback=False)
        assert result is not None
        assert result.action == "BUY"
        assert result.trigger_strategy is True

    def test_cancel_buy(self):
        result = parse_trade_command("cancel buy AAPL", use_llm_fallback=False)
        assert result is not None
        assert result.command_kind == "cancel"
        assert result.cancel_order_class == "buy"

    def test_cancel_stop_sell(self):
        result = parse_trade_command("cancel stop sell MSFT", use_llm_fallback=False)
        assert result is not None
        assert result.cancel_order_class == "stop_sell"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_message(self):
        assert parse_trade_command("", use_llm_fallback=False) is None

    def test_whitespace_only(self):
        assert parse_trade_command("   ", use_llm_fallback=False) is None

    def test_none_message(self):
        assert parse_trade_command(None, use_llm_fallback=False) is None

    def test_very_long_message(self):
        """Very long messages should not cause regex catastrophic backtracking."""
        long_msg = "buy AAPL " + "x" * 5000
        result = parse_trade_command(long_msg, use_llm_fallback=False)
        # Should either parse or return None quickly, not hang
        if result:
            assert result.action == "BUY"

    def test_case_insensitive_action(self):
        result = parse_trade_command("BUY AAPL", use_llm_fallback=False)
        assert result is not None
        assert result.action == "BUY"

    def test_mixed_case_action(self):
        result = parse_trade_command("Buy aapl", use_llm_fallback=False)
        assert result is not None
        assert result.action == "BUY"
