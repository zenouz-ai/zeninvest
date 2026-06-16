"""Tests for unified gain/day 3-class outcome labeling (v6)."""

from __future__ import annotations

from src.agents.reporting.outcome_classification import (
    EXIT_REASON_TRAILING_STOP,
    classification_rules_dict,
    derive_label_3class,
    explain_classification,
    gain_per_day_pct,
    is_big_loser,
    is_big_winner,
    is_stall_label,
    label_from_gain_per_day,
)


def test_winner_band_examples():
    assert derive_label_3class(pnl_pct=5.0, holding_days=20.0, exit_reason="manual_or_strategy") == "big_winner"
    assert derive_label_3class(pnl_pct=10.0, holding_days=40.0, exit_reason="manual_or_strategy") == "big_winner"
    assert derive_label_3class(pnl_pct=9.6, holding_days=5.9, exit_reason=EXIT_REASON_TRAILING_STOP) == "big_winner"
    assert is_big_winner(9.6, 5.9)
    assert gain_per_day_pct(5.0, 20.0) == 0.25


def test_stall_band_examples():
    assert derive_label_3class(pnl_pct=6.0, holding_days=25.0, exit_reason="manual_or_strategy") == "stall"
    assert derive_label_3class(pnl_pct=5.0, holding_days=24.0, exit_reason="manual_or_strategy") == "stall"
    assert derive_label_3class(pnl_pct=10.0, holding_days=59.0, exit_reason="manual_or_strategy") == "stall"
    assert derive_label_3class(pnl_pct=-2.0, holding_days=50.0, exit_reason="hard_stop") == "stall"
    assert is_stall_label(6.0, 25.0)


def test_loser_band_examples():
    assert derive_label_3class(pnl_pct=-5.0, holding_days=10.0, exit_reason="hard_stop") == "big_loser"
    assert derive_label_3class(pnl_pct=-9.64, holding_days=51.9, exit_reason="hard_stop") == "big_loser"
    assert derive_label_3class(pnl_pct=-6.95, holding_days=25.9, exit_reason="hard_stop") == "big_loser"
    assert derive_label_3class(pnl_pct=-5.0, holding_days=5.0, exit_reason="hard_stop") == "big_loser"
    assert is_big_loser(-5.0, 10.0)


def test_boundary_winner_at_exact_threshold():
    assert label_from_gain_per_day(5.0, 20.0) == "big_winner"
    assert label_from_gain_per_day(6.0, 25.0) == "stall"


def test_boundary_stall_floor():
    assert label_from_gain_per_day(-0.05, 1.0) == "stall"
    assert label_from_gain_per_day(-0.06, 1.0) == "big_loser"


def test_tiny_scalp_can_be_winner():
    assert derive_label_3class(pnl_pct=1.0, holding_days=3.0, exit_reason="manual_or_strategy") == "big_winner"


def test_strong_slow_winner_no_cap():
    assert derive_label_3class(pnl_pct=27.3, holding_days=51.9, exit_reason=EXIT_REASON_TRAILING_STOP) == "big_winner"
    assert derive_label_3class(pnl_pct=101.0, holding_days=400.0, exit_reason="manual_or_strategy") == "big_winner"


def test_explain_winner_and_loser():
    win_text = explain_classification(
        pnl_pct=9.6,
        holding_days=5.9,
        exit_reason=EXIT_REASON_TRAILING_STOP,
        label_3class="big_winner",
        result="win",
    )
    assert "big_winner" in win_text
    assert "gain/day" in win_text

    lose_text = explain_classification(
        pnl_pct=-9.64,
        holding_days=51.9,
        exit_reason="hard_stop",
        label_3class="big_loser",
        result="loss",
    )
    assert "big_loser" in lose_text
    assert "gain/day" in lose_text


def test_classification_rules_v6_defaults():
    rules = classification_rules_dict()
    assert rules["success_min_profit_per_day_pct"] == 0.25
    assert rules["stall_min_gain_per_day_pct"] == -0.05


def test_hard_stop_without_realized_only_when_allowed():
    assert (
        derive_label_3class(
            pnl_pct=None,
            holding_days=None,
            exit_reason="hard_stop",
            allow_stop_without_realized=True,
        )
        == "big_loser"
    )
    assert (
        derive_label_3class(
            pnl_pct=None,
            holding_days=None,
            exit_reason="hard_stop",
            allow_stop_without_realized=False,
        )
        == "stall"
    )
