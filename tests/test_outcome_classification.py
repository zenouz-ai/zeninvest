"""Tests for shared trade outcome classification."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.reporting.outcome_classification import (
    EXIT_REASON_HARD_STOP,
    EXIT_REASON_TRAILING_STOP,
    classification_rules_dict,
    derive_label_3class,
    exit_label,
    explain_classification,
    infer_exit_reason,
    simple_result,
    weighted_quote_return_pct,
)


def test_infer_exit_reason_losing_stop():
    sell_ts = datetime(2025, 4, 1, 15, 0, tzinfo=timezone.utc)
    stops = [{"timestamp": sell_ts, "status": "filled", "trigger_reason": "hard_stop"}]
    assert (
        infer_exit_reason(
            sell_timestamp=sell_ts,
            buy_warning_note=None,
            stop_adjustments=stops,
            pnl_pct=-5.0,
            sell_order_type="stop",
        )
        == EXIT_REASON_HARD_STOP
    )


def test_infer_exit_reason_profitable_trailing_stop():
    sell_ts = datetime(2026, 6, 8, 14, 0, tzinfo=timezone.utc)
    stops = [{"timestamp": sell_ts, "status": "filled", "trigger_reason": "trailing_ratchet"}]
    assert (
        infer_exit_reason(
            sell_timestamp=sell_ts,
            buy_warning_note=None,
            stop_adjustments=stops,
            pnl_pct=27.3,
            sell_order_type="stop",
        )
        == EXIT_REASON_TRAILING_STOP
    )


def test_explain_classification_stall_win_band():
    text = explain_classification(
        pnl_pct=6.0,
        holding_days=25.0,
        exit_reason=EXIT_REASON_TRAILING_STOP,
        label_3class="stall",
        result="win",
    )
    assert "WIN" in text
    assert "stall" in text
    assert "gain/day" in text


def test_classification_rules_dict_defaults():
    rules = classification_rules_dict()
    assert rules["success_min_profit_per_day_pct"] == 0.25
    assert rules["stall_min_gain_per_day_pct"] == -0.05
    assert len(rules["exit_reasons"]) == 4


def test_derive_label_3class_profitable_stop_strong_slow_winner():
    assert (
        derive_label_3class(
            pnl_pct=27.3,
            holding_days=51.9,
            exit_reason=EXIT_REASON_TRAILING_STOP,
        )
        == "big_winner"
    )


def test_derive_label_3class_losing_stop_is_big_loser():
    assert (
        derive_label_3class(
            pnl_pct=-8.0,
            holding_days=10.0,
            exit_reason=EXIT_REASON_HARD_STOP,
        )
        == "big_loser"
    )


def test_derive_label_3class_hard_stop_without_realized_only_when_allowed():
    assert (
        derive_label_3class(
            pnl_pct=None,
            holding_days=None,
            exit_reason=EXIT_REASON_HARD_STOP,
            allow_stop_without_realized=True,
        )
        == "big_loser"
    )
    assert (
        derive_label_3class(
            pnl_pct=None,
            holding_days=None,
            exit_reason=EXIT_REASON_HARD_STOP,
            allow_stop_without_realized=False,
        )
        == "stall"
    )


def test_simple_result_and_exit_label():
    assert simple_result(5.0) == "win"
    assert simple_result(-3.0) == "loss"
    assert simple_result(0.2) == "flat"
    assert exit_label(EXIT_REASON_HARD_STOP) == "Stop loss exit"
    assert exit_label(EXIT_REASON_TRAILING_STOP) == "Trailing stop (profit lock)"
    assert exit_label("manual_or_strategy", sell_order_type="market") == "Market / strategy exit"


def test_weighted_quote_return_pct():
    legs = [(24.0, 17.49)]
    assert weighted_quote_return_pct(legs, 16.09) == pytest.approx(-8.0046, rel=1e-3)
