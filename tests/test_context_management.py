"""Tests for SessionContext — serialization, merging, compaction, inheritance."""

import os

os.environ.setdefault("INVESTMENT_AGENT_USE_INMEMORY_DB", "1")

import pytest

from src.agents.conversation.context import SessionContext, TickerContext


# ---------------------------------------------------------------------------
# TickerContext
# ---------------------------------------------------------------------------


class TestTickerContext:
    def test_round_trip(self):
        tc = TickerContext(ticker="AAPL_US_EQ", last_mentioned_turn=3, last_action="BUY")
        d = tc.to_dict()
        tc2 = TickerContext.from_dict(d)
        assert tc2.ticker == "AAPL_US_EQ"
        assert tc2.last_mentioned_turn == 3
        assert tc2.last_action == "BUY"

    def test_from_dict_defaults(self):
        tc = TickerContext.from_dict({"ticker": "MSFT_US_EQ"})
        assert tc.last_mentioned_turn == 0
        assert tc.last_action is None


# ---------------------------------------------------------------------------
# SessionContext — serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_json_round_trip(self):
        ctx = SessionContext(
            last_subject_tickers=["AAPL_US_EQ"],
            watchlist=["NVDA_US_EQ"],
            turn_count=5,
        )
        ctx.active_tickers["AAPL_US_EQ"] = TickerContext(
            ticker="AAPL_US_EQ", last_mentioned_turn=3
        )
        json_str = ctx.to_json()
        restored = SessionContext.from_json(json_str)
        assert restored.last_subject_tickers == ["AAPL_US_EQ"]
        assert restored.watchlist == ["NVDA_US_EQ"]
        assert restored.turn_count == 5
        assert "AAPL_US_EQ" in restored.active_tickers

    def test_from_json_none(self):
        ctx = SessionContext.from_json(None)
        assert ctx.turn_count == 0
        assert ctx.last_subject_tickers == []

    def test_from_json_invalid_string(self):
        ctx = SessionContext.from_json("not json")
        assert ctx.turn_count == 0

    def test_from_json_legacy_dict(self):
        """Legacy context dicts only have last_subject_tickers."""
        ctx = SessionContext.from_json({"last_subject_tickers": ["AAPL_US_EQ"]})
        assert ctx.last_subject_tickers == ["AAPL_US_EQ"]
        assert ctx.turn_count == 0

    def test_to_dict_and_back(self):
        ctx = SessionContext(
            last_subject_tickers=["A"],
            last_selection_result={"winner": "A"},
            pending_actions=[1, 2],
            previous_session_id=42,
        )
        d = ctx.to_dict()
        restored = SessionContext.from_json(d)
        assert restored.last_selection_result == {"winner": "A"}
        assert restored.pending_actions == [1, 2]
        assert restored.previous_session_id == 42


# ---------------------------------------------------------------------------
# SessionContext — merging
# ---------------------------------------------------------------------------


class TestMerge:
    def test_merge_subject_tickers(self):
        ctx = SessionContext(last_subject_tickers=["OLD"])
        ctx.merge({"last_subject_tickers": ["NEW"]})
        assert ctx.last_subject_tickers == ["NEW"]

    def test_merge_preserves_unmentioned_fields(self):
        ctx = SessionContext(watchlist=["W1"], turn_count=3)
        ctx.merge({"last_subject_tickers": ["T1"]})
        assert ctx.watchlist == ["W1"]
        assert ctx.turn_count == 3

    def test_merge_promotes_subject_to_active_tickers(self):
        ctx = SessionContext(turn_count=2)
        ctx.merge({"last_subject_tickers": ["AAPL_US_EQ"]})
        assert "AAPL_US_EQ" in ctx.active_tickers
        assert ctx.active_tickers["AAPL_US_EQ"].last_mentioned_turn == 2

    def test_merge_updates_existing_active_ticker_turn(self):
        ctx = SessionContext(turn_count=5)
        ctx.active_tickers["AAPL_US_EQ"] = TickerContext(
            ticker="AAPL_US_EQ", last_mentioned_turn=1
        )
        ctx.merge({"last_subject_tickers": ["AAPL_US_EQ"]})
        assert ctx.active_tickers["AAPL_US_EQ"].last_mentioned_turn == 5

    def test_merge_active_tickers_dict(self):
        ctx = SessionContext()
        ctx.merge({
            "active_tickers": {
                "MSFT_US_EQ": {"ticker": "MSFT_US_EQ", "last_action": "REVIEW"},
            }
        })
        assert "MSFT_US_EQ" in ctx.active_tickers
        assert ctx.active_tickers["MSFT_US_EQ"].last_action == "REVIEW"

    def test_merge_empty_update(self):
        ctx = SessionContext(last_subject_tickers=["A"])
        ctx.merge({})
        assert ctx.last_subject_tickers == ["A"]

    def test_merge_none_update(self):
        ctx = SessionContext(last_subject_tickers=["A"])
        ctx.merge(None)
        assert ctx.last_subject_tickers == ["A"]


# ---------------------------------------------------------------------------
# SessionContext — compaction
# ---------------------------------------------------------------------------


class TestCompaction:
    def test_needs_compaction_false_initially(self):
        ctx = SessionContext(turn_count=3)
        assert ctx.needs_compaction() is False

    def test_needs_compaction_true_after_5_turns(self):
        ctx = SessionContext(turn_count=5, last_compacted_at_turn=0)
        assert ctx.needs_compaction() is True

    def test_compact_resets_counter(self):
        ctx = SessionContext(turn_count=10, last_compacted_at_turn=0)
        ctx.compact("Summary of turns 1-10")
        assert ctx.conversation_summary == "Summary of turns 1-10"
        assert ctx.last_compacted_at_turn == 10
        assert ctx.needs_compaction() is False

    def test_custom_interval(self):
        ctx = SessionContext(turn_count=3, last_compacted_at_turn=0)
        assert ctx.needs_compaction(interval=3) is True
        assert ctx.needs_compaction(interval=5) is False


# ---------------------------------------------------------------------------
# SessionContext — cross-session inheritance
# ---------------------------------------------------------------------------


class TestInheritance:
    def test_inherit_active_tickers(self):
        prev = SessionContext()
        prev.active_tickers["AAPL_US_EQ"] = TickerContext(
            ticker="AAPL_US_EQ", last_action="BUY"
        )
        prev.watchlist = ["NVDA_US_EQ"]

        new = SessionContext()
        new.inherit_from(prev)
        assert "AAPL_US_EQ" in new.active_tickers
        assert new.watchlist == ["NVDA_US_EQ"]

    def test_inherit_does_not_overwrite_existing(self):
        prev = SessionContext()
        prev.active_tickers["AAPL_US_EQ"] = TickerContext(
            ticker="AAPL_US_EQ", last_action="SELL"
        )

        new = SessionContext()
        new.active_tickers["AAPL_US_EQ"] = TickerContext(
            ticker="AAPL_US_EQ", last_action="BUY"
        )
        new.inherit_from(prev)
        assert new.active_tickers["AAPL_US_EQ"].last_action == "BUY"

    def test_clear_inherited(self):
        ctx = SessionContext(
            last_subject_tickers=["A"],
            watchlist=["B"],
            conversation_summary="old summary",
        )
        ctx.active_tickers["A"] = TickerContext(ticker="A")
        ctx.clear_inherited()
        assert ctx.active_tickers == {}
        assert ctx.watchlist == []
        assert ctx.last_subject_tickers == []
        assert ctx.conversation_summary == ""


# ---------------------------------------------------------------------------
# SessionContext — legacy compatibility
# ---------------------------------------------------------------------------


class TestLegacyCompat:
    def test_to_legacy_dict(self):
        ctx = SessionContext(
            last_subject_tickers=["AAPL_US_EQ"],
            last_selection_tickers=["NVDA_US_EQ"],
            watchlist=["MSFT_US_EQ"],
        )
        legacy = ctx.to_legacy_dict()
        assert legacy == {
            "last_subject_tickers": ["AAPL_US_EQ"],
            "last_selection_tickers": ["NVDA_US_EQ"],
        }
        # Legacy dict should not contain extra fields
        assert "watchlist" not in legacy

    def test_increment_turn(self):
        ctx = SessionContext(turn_count=3)
        ctx.increment_turn()
        assert ctx.turn_count == 4
