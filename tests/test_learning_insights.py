"""Unit tests for ``src.learning.insights`` (pure-data analytics helpers)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from src.learning.insights import (
    compute_baseline_lift,
    compute_conviction_calibration,
    compute_conviction_vs_pnl_scatter,
    compute_feature_importance,
    compute_horizon_distribution,
    compute_label_distribution,
    compute_macro_regime_outcomes,
    compute_realized_pnl_buckets,
)


def _build_synthetic_df(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    base_ts = datetime(2026, 3, 1, tzinfo=timezone.utc)
    rows: list[dict] = []
    for i in range(n):
        bucket = i % 4
        if bucket == 0:
            label = "big_winner"
            pnl = 12.0
            ret = 11.0
            horizon = 8.0
        elif bucket == 1:
            label = "big_loser"
            pnl = -12.0
            ret = -10.5
            horizon = 4.0
        elif bucket == 2:
            label = "stall"
            pnl = 0.5
            ret = 0.5
            horizon = 18.0
        else:
            label = "neutral"
            pnl = float(rng.normal(0, 2))
            ret = float(rng.normal(0, 2))
            horizon = 9.0
        rows.append(
            {
                "cycle_id": f"cycle-{i:03d}",
                "ticker": "AAPL_US_EQ",
                "decision_ts": base_ts + timedelta(days=i),
                "conviction": float(45 + (i % 5) * 10),
                "macro_regime": ["RISK_ON", "RISK_OFF", "NEUTRAL"][i % 3],
                "label_3class": label,
                "realized_pnl_pct": pnl if bucket != 3 else None,
                "realized_holding_days": horizon if bucket != 3 else None,
                "ret_30d": ret,
            }
        )
    return pd.DataFrame(rows)


def test_label_distribution_returns_counts_and_priors() -> None:
    df = _build_synthetic_df()
    table = compute_label_distribution(df)
    assert table.summary["total"] == len(df)
    priors = table.summary["label_priors"]
    assert pytest.approx(sum(priors.values()), rel=1e-6) == 1.0
    assert "big_winner" in priors
    assert priors["big_winner"] == pytest.approx(0.25, rel=0.05)


def test_conviction_calibration_flags_monotonicity() -> None:
    df = _build_synthetic_df()
    calib = compute_conviction_calibration(df)
    assert calib.summary["n_rows"] == len(df)
    assert "monotonic" in calib.summary
    assert "global_win_rate" in calib.summary
    assert 0.0 <= calib.summary["global_win_rate"] <= 1.0


def test_realized_pnl_buckets_have_correct_totals() -> None:
    df = _build_synthetic_df()
    pnl = compute_realized_pnl_buckets(df)
    assert pnl.summary["n_closed"] > 0
    assert pnl.summary["big_winner_pct"] > 0
    assert pnl.summary["big_loser_pct"] > 0


def test_horizon_distribution_groups_per_label() -> None:
    df = _build_synthetic_df()
    horizon = compute_horizon_distribution(df)
    assert not horizon.df.empty
    assert "label" in horizon.df.columns
    assert horizon.summary["n_closed"] > 0


def test_macro_regime_outcomes_returns_one_row_per_regime() -> None:
    df = _build_synthetic_df()
    regime = compute_macro_regime_outcomes(df)
    assert {"RISK_ON", "RISK_OFF", "NEUTRAL"}.issubset(set(regime.df["regime"]))
    assert regime.summary["n_rows"] == len(df)


def test_feature_importance_returns_top_k() -> None:
    imp = compute_feature_importance({"a": 0.4, "b": 0.3, "c": 0.2, "d": 0.1}, top_n=2)
    assert len(imp.df) == 2
    assert imp.df.iloc[0]["feature"] == "a"
    assert imp.summary["top_n"] == 2


def test_baseline_lift_includes_majority_policy() -> None:
    df = _build_synthetic_df()
    lift = compute_baseline_lift(df)
    policies = set(lift.df["policy"])
    assert "majority" in policies
    assert "conviction_only" in policies


def test_conviction_vs_pnl_scatter_returns_correlation() -> None:
    df = _build_synthetic_df()
    scatter = compute_conviction_vs_pnl_scatter(df)
    assert scatter.summary["n_closed"] > 0
    assert isinstance(scatter.summary["pearson_correlation"], float)
