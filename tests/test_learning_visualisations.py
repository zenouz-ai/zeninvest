"""Unit tests for ``src.learning.visualisations``.

Skips cleanly when matplotlib is not installed (no ``learning`` extra).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

pytest.importorskip("matplotlib")


def _build_df() -> pd.DataFrame:
    base_ts = datetime(2026, 3, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(60):
        bucket = i % 4
        rows.append(
            {
                "cycle_id": f"cycle-{i:03d}",
                "ticker": "AAPL_US_EQ",
                "decision_ts": base_ts + timedelta(days=i),
                "conviction": float(40 + (i % 6) * 10),
                "macro_regime": ["RISK_ON", "RISK_OFF", "NEUTRAL"][i % 3],
                "label_3class": ["big_winner", "big_loser", "stall", "neutral"][bucket],
                "realized_pnl_pct": [12.0, -12.0, 0.5, None][bucket],
                "realized_holding_days": [8.0, 4.0, 18.0, None][bucket],
                "ret_30d": [11.0, -10.5, 0.5, 0.0][bucket],
            }
        )
    return pd.DataFrame(rows)


def test_render_insight_charts_writes_png_files(tmp_path) -> None:
    from src.learning.visualisations import render_insight_charts

    df = _build_df()
    paths = render_insight_charts(df=df, gbm_result=None, calibrator=None, output_dir=tmp_path)
    assert len(paths) >= 5  # GBM-dependent charts are skipped when no result is given
    for name, path in paths.items():
        assert name.endswith(".png")
        size = (tmp_path / name).stat().st_size
        assert size > 1024, f"{name} is suspiciously small ({size} bytes)"
    assert (tmp_path / "summary.json").exists()


def test_render_insight_charts_with_gbm_stub(tmp_path) -> None:
    from src.learning.visualisations import render_insight_charts

    df = _build_df()

    class _StubGBM:
        feature_importance = {"alpha": 0.45, "beta": 0.30, "gamma": 0.25}
        decile_lift = [
            {"decile": d, "mean_ret_30d_pct": (d - 4) * 0.4, "count": 5} for d in range(10)
        ]
        aggregate_metrics = {"accuracy": 0.5, "auc": {"big_winner": 0.6}, "per_class_recall": {"big_winner": 0.5}}
        out_of_fold_predictions = None

    paths = render_insight_charts(df=df, gbm_result=_StubGBM(), calibrator=None, output_dir=tmp_path)
    assert "06_gbm_feature_importance.png" in paths
    assert "07_decile_lift.png" in paths
