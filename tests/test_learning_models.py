"""Tests for the trained models in src.learning.models.

Skips cleanly when the optional ``learning`` poetry extra is not installed.
Install with ``poetry install --with learning`` to exercise this suite locally.

``importorskip`` must run before importing any submodule that loads sklearn.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sklearn")
pytest.importorskip("lightgbm")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.learning.dataset.splits import WalkForwardSplitter  # noqa: E402
from src.learning.models.calibration import (  # noqa: E402
    DEFAULT_BIN_EDGES,
    fit_conviction_calibrator,
)


def _synthetic_dataset(n: int = 600, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    decision_ts = pd.date_range("2026-01-01", periods=n, freq="6h")
    conviction = rng.integers(40, 95, n)
    uov_ewma = rng.normal(0.4, 0.5, n)
    vix_level = rng.normal(18, 4, n)
    realized_vol_60d = rng.uniform(0.1, 0.6, n)
    risk_triggered = rng.integers(0, 4, n)
    macro_confidence = rng.uniform(0.2, 0.9, n)
    # Signal: higher conviction + higher uov + lower vix -> higher win probability.
    score = (
        (conviction - 60) * 0.04
        + uov_ewma * 1.5
        + macro_confidence * 0.8
        - (vix_level - 18) * 0.05
        - risk_triggered * 0.4
    )
    probs = 1 / (1 + np.exp(-score))
    rolls = rng.uniform(size=n)
    labels = np.where(
        rolls < probs * 0.55,
        "big_winner",
        np.where(rolls < probs * 0.55 + 0.15, "stall", "big_loser"),
    )
    # 30-day returns roughly aligned with the score.
    ret_30d = score * 4 + rng.normal(0, 6, n)
    return pd.DataFrame(
        {
            "cycle_id": [f"cycle-{i}" for i in range(n)],
            "ticker": [f"T{(i % 17)}_US_EQ" for i in range(n)],
            "decision_ts": decision_ts,
            "conviction": conviction,
            "uov_ewma": uov_ewma,
            "vix_level": vix_level,
            "realized_vol_60d": realized_vol_60d,
            "risk_triggered_rules_count": risk_triggered,
            "macro_confidence": macro_confidence,
            "ret_30d": ret_30d,
            "mtm_max_drawdown_30d": ret_30d - 5,
            "mtm_max_runup_30d": ret_30d + 5,
            "realized_pnl_pct": ret_30d * 0.5,
            "realized_holding_days": rng.integers(1, 40, n).astype(float),
            "exit_reason": "n/a",
            "actually_traded": True,
            "label_3class": labels,
        }
    )


def test_conviction_calibrator_emits_curve_and_isotonic() -> None:
    df = _synthetic_dataset(600)
    calibrator = fit_conviction_calibrator(df)
    assert calibrator.curve.bin_labels
    # Predictions should rise (loosely) with conviction.
    low = calibrator.predict_one(50)
    high = calibrator.predict_one(85)
    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0
    assert high >= low - 0.05  # tolerate isotonic plateau
    # Curve metadata should reflect the canonical US-2.1 bins.
    assert calibrator.curve.bin_edges == list(DEFAULT_BIN_EDGES)


def test_train_lightgbm_walk_forward_returns_metrics() -> None:
    pytest.importorskip("lightgbm")
    from src.learning.models.gbm import train_lightgbm_walk_forward

    df = _synthetic_dataset(700)
    splits = WalkForwardSplitter(embargo_days=10, test_window_days=20).split(df["decision_ts"].tolist())
    assert splits.n_folds >= 1
    result = train_lightgbm_walk_forward(df, walk_forward=splits)
    assert result.feature_columns
    assert result.aggregate_metrics["n_folds"] >= 1
    # Confusion matrix is square and full.
    classes = result.classes
    for cls in classes:
        assert cls in result.confusion_matrix
        for inner in classes:
            assert inner in result.confusion_matrix[cls]
    assert result.feature_importance


def test_train_stall_model_handles_synthetic_dataset() -> None:
    pytest.importorskip("lightgbm")
    from src.learning.models.stall import train_stall_model

    df = _synthetic_dataset(500)
    splits = WalkForwardSplitter(embargo_days=10, test_window_days=20).split(df["decision_ts"].tolist())
    result = train_stall_model(df, walk_forward=splits)
    # Either trained folds or skipped gracefully.
    assert result.aggregate_metrics is not None
    assert result.feature_columns
