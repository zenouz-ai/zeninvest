"""Matplotlib chart rendering for the learning pipeline.

Produces a fixed set of PNGs under ``data/learning/reports/<run_id>/insights/``
which the dashboard, ``docs/LEARNING_INSIGHTS.md`` and the HTML report all
embed.

Charts are deliberately monochrome-friendly with a tight 800x500 canvas
suitable for both the dashboard ``<img>`` embed and dark-mode markdown
rendering.

This module is the only place matplotlib is imported. Callers should wrap
``render_insight_charts`` in a try/except so that environments without the
``learning`` poetry extra still complete training successfully.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

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
from src.utils.logger import get_logger

logger = get_logger("learning.visualisations")


# Public ordering used by the HTML report and the docs index.
CHART_FILES: tuple[str, ...] = (
    "01_label_distribution.png",
    "02_conviction_calibration.png",
    "03_realized_pnl_distribution.png",
    "04_horizon_vs_label.png",
    "05_macro_regime_outcomes.png",
    "06_gbm_feature_importance.png",
    "07_decile_lift.png",
    "08_conviction_vs_pnl.png",
    "09_baseline_vs_gbm.png",
)


def _lazy_matplotlib():
    try:  # pragma: no cover - import gate
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return matplotlib, plt
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "matplotlib is required to render insight charts. "
            "Install with `poetry install --with learning`."
        ) from exc


def render_insight_charts(
    *,
    df: pd.DataFrame,
    gbm_result: Any | None = None,
    calibrator: Any | None = None,
    output_dir: str | Path,
) -> dict[str, str]:
    """Render the full insight chart set and return ``{name: absolute_path}``."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _, plt = _lazy_matplotlib()

    written: dict[str, str] = {}

    written.update(_render_label_distribution(plt, df, output_dir))
    written.update(_render_conviction_calibration(plt, df, calibrator, output_dir))
    written.update(_render_realized_pnl(plt, df, output_dir))
    written.update(_render_horizon_distribution(plt, df, output_dir))
    written.update(_render_macro_regimes(plt, df, output_dir))
    written.update(_render_feature_importance(plt, gbm_result, output_dir))
    written.update(_render_decile_lift(plt, gbm_result, output_dir))
    written.update(_render_conviction_vs_pnl(plt, df, output_dir))
    written.update(_render_baseline_vs_gbm(plt, df, gbm_result, output_dir))

    summary: dict[str, Any] = {
        "files": list(written.keys()),
        "paths": dict(written),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return dict(written)


# ---------------------------------------------------------------------------
# Individual chart renderers
# ---------------------------------------------------------------------------


def _save(plt, fig, output_dir: Path, name: str) -> str:
    path = output_dir / name
    fig.tight_layout()
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logger.info("Wrote %s", path)
    return str(path)


def _render_label_distribution(plt, df: pd.DataFrame, output_dir: Path) -> dict[str, str]:
    insight = compute_label_distribution(df)
    if insight.df.empty:
        return {}
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    labels = insight.df["label_3class"].astype(str).tolist()
    counts = insight.df["count"].astype(int).tolist()
    bars = ax.bar(labels, counts)
    ax.set_title("Label distribution (Mar 5 to May 12, 2026)")
    ax.set_ylabel("rows")
    ax.set_xlabel("3-class label")
    for bar, pct in zip(bars, insight.df["pct"].astype(float).tolist()):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{int(bar.get_height())}\n({pct:.1f}%)",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.margins(y=0.18)
    name = "01_label_distribution.png"
    return {name: _save(plt, fig, output_dir, name)}


def _render_conviction_calibration(
    plt, df: pd.DataFrame, calibrator: Any | None, output_dir: Path
) -> dict[str, str]:
    insight = compute_conviction_calibration(df)
    if insight.df.empty:
        return {}
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    bins = insight.df["bin"].astype(str).tolist()
    rates = insight.df["empirical_win_rate"].astype(float).tolist()
    counts = insight.df["count"].astype(int).tolist()

    ax.bar(bins, rates, alpha=0.65, label="Empirical win rate")
    ax.set_ylim(0, max(rates + [insight.summary.get("global_win_rate", 0.0) * 2 + 0.05]) + 0.05)
    ax.set_title("Conviction calibration: empirical vs predicted win rate")
    ax.set_ylabel("Win rate (big_winner share)")
    ax.set_xlabel("Conviction bin")
    ax.axhline(
        insight.summary.get("global_win_rate", 0.0),
        linestyle="--",
        linewidth=1,
        label=f"Global win rate ({insight.summary.get('global_win_rate', 0.0)*100:.1f}%)",
    )
    # Overlay isotonic / calibrator predictions when available.
    if calibrator is not None:
        try:
            mid_points = []
            for label in bins:
                left = label.split(",")[0].strip("[(")
                right = label.split(",")[-1].strip(")]")
                mid = (float(left) + float(right)) / 2
                mid_points.append(mid)
            preds = list(calibrator.predict_win_rate(mid_points))
            ax.plot(bins, preds, marker="o", linewidth=1.5, label="Calibrator prediction")
        except (AttributeError, TypeError, ValueError) as exc:  # pragma: no cover
            logger.debug("Skipping calibrator overlay: %s", exc)
    for x, count in enumerate(counts):
        ax.text(x, 0.005, f"n={count}", ha="center", va="bottom", fontsize=8)
    ax.legend(loc="upper left", fontsize=8)
    name = "02_conviction_calibration.png"
    return {name: _save(plt, fig, output_dir, name)}


def _render_realized_pnl(plt, df: pd.DataFrame, output_dir: Path) -> dict[str, str]:
    insight = compute_realized_pnl_buckets(df)
    if insight.df.empty:
        return {}
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    buckets = insight.df["bucket"].astype(str).tolist()
    counts = insight.df["count"].astype(int).tolist()
    ax.bar(buckets, counts)
    ax.set_xticks(range(len(buckets)))
    ax.set_xticklabels(buckets, rotation=30, ha="right")
    ax.set_title(
        "Realized PnL distribution "
        f"(n={insight.summary['n_closed']}, mean {insight.summary['mean_pnl_pct']:.2f}%, "
        f"big winners {insight.summary['big_winner_pct']:.1f}%, "
        f"big losers {insight.summary['big_loser_pct']:.1f}%)"
    )
    ax.set_ylabel("Closed trades")
    ax.set_xlabel("PnL bucket (%)")
    name = "03_realized_pnl_distribution.png"
    return {name: _save(plt, fig, output_dir, name)}


def _render_horizon_distribution(plt, df: pd.DataFrame, output_dir: Path) -> dict[str, str]:
    insight = compute_horizon_distribution(df)
    if insight.df.empty:
        return {}
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    labels = insight.df["label"].astype(str).tolist()
    means = insight.df["mean"].astype(float).tolist()
    stds = insight.df["std"].astype(float).tolist()
    counts = insight.df["count"].astype(int).tolist()
    ax.bar(labels, means, yerr=stds, capsize=4)
    for x, (mean, count) in enumerate(zip(means, counts)):
        ax.text(x, mean, f"  {mean:.1f}d (n={count})", ha="center", va="bottom", fontsize=9)
    ax.set_title("Holding days by realized outcome (closed trades)")
    ax.set_ylabel("Mean holding days")
    ax.set_xlabel("Realized label")
    ax.margins(y=0.2)
    name = "04_horizon_vs_label.png"
    return {name: _save(plt, fig, output_dir, name)}


def _render_macro_regimes(plt, df: pd.DataFrame, output_dir: Path) -> dict[str, str]:
    insight = compute_macro_regime_outcomes(df)
    if insight.df.empty:
        return {}
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    regimes = insight.df["regime"].astype(str).tolist()
    width = 0.35
    x = np.arange(len(regimes))
    ax.bar(x - width / 2, insight.df["win_rate"].astype(float), width=width, label="Big winner rate")
    ax.bar(x + width / 2, insight.df["loss_rate"].astype(float), width=width, label="Big loser rate")
    ax.set_xticks(x)
    ax.set_xticklabels(regimes)
    for idx, (regime, n) in enumerate(zip(regimes, insight.df["n"].astype(int))):
        ax.text(idx, 0.005, f"n={n}", ha="center", va="bottom", fontsize=8)
    ax.set_title("Outcome split by macro regime")
    ax.set_ylabel("Share of rows")
    ax.legend(fontsize=8)
    name = "05_macro_regime_outcomes.png"
    return {name: _save(plt, fig, output_dir, name)}


def _render_feature_importance(plt, gbm_result: Any | None, output_dir: Path) -> dict[str, str]:
    if gbm_result is None or not getattr(gbm_result, "feature_importance", None):
        return {}
    insight = compute_feature_importance(dict(gbm_result.feature_importance))
    if insight.df.empty:
        return {}
    fig, ax = plt.subplots(figsize=(7.5, 6.0))
    df = insight.df.iloc[::-1]
    ax.barh(df["feature"].astype(str), df["relative_gain"].astype(float) * 100.0)
    ax.set_title("LightGBM top-20 feature importance (relative gain, walk-forward mean)")
    ax.set_xlabel("Relative gain (%)")
    name = "06_gbm_feature_importance.png"
    return {name: _save(plt, fig, output_dir, name)}


def _render_decile_lift(plt, gbm_result: Any | None, output_dir: Path) -> dict[str, str]:
    if gbm_result is None or not getattr(gbm_result, "decile_lift", None):
        return {}
    rows = list(gbm_result.decile_lift)
    if not rows:
        return {}
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    deciles = [r["decile"] for r in rows]
    means = [r["mean_ret_30d_pct"] for r in rows]
    counts = [r["count"] for r in rows]
    ax.bar(deciles, means)
    for x, (m, c) in enumerate(zip(means, counts)):
        ax.text(x, m, f"  n={c}", ha="center", va="bottom", fontsize=8)
    ax.set_title("Out-of-fold decile lift on (winner - loser) probability spread")
    ax.set_xlabel("Decile (highest spread = 9)")
    ax.set_ylabel("Mean ret_30d (%)")
    ax.axhline(0, linewidth=1, linestyle="--")
    name = "07_decile_lift.png"
    return {name: _save(plt, fig, output_dir, name)}


def _render_conviction_vs_pnl(plt, df: pd.DataFrame, output_dir: Path) -> dict[str, str]:
    insight = compute_conviction_vs_pnl_scatter(df)
    if insight.df.empty:
        return {}
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    ax.scatter(
        insight.df["conviction"].astype(float),
        insight.df["realized_pnl_pct"].astype(float),
        s=14,
        alpha=0.55,
    )
    ax.axhline(0, linewidth=1, linestyle="--")
    ax.set_title(
        "Conviction vs realized PnL (Pearson r = "
        f"{insight.summary.get('pearson_correlation', 0.0):.3f}, "
        f"n={insight.summary['n_closed']})"
    )
    ax.set_xlabel("Conviction")
    ax.set_ylabel("Realized PnL (%)")
    name = "08_conviction_vs_pnl.png"
    return {name: _save(plt, fig, output_dir, name)}


def _render_baseline_vs_gbm(
    plt, df: pd.DataFrame, gbm_result: Any | None, output_dir: Path
) -> dict[str, str]:
    gbm_agg = getattr(gbm_result, "aggregate_metrics", None) if gbm_result else None
    gbm_oof = getattr(gbm_result, "out_of_fold_predictions", None) if gbm_result else None
    insight = compute_baseline_lift(
        df,
        gbm_aggregate_metrics=gbm_agg,
        gbm_oof=gbm_oof,
    )
    if insight.df.empty:
        return {}
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    policies = insight.df["policy"].astype(str).tolist()
    x = np.arange(len(policies))
    width = 0.25
    ax.bar(x - width, insight.df["macro_f1"].astype(float), width, label="Macro F1")
    ax.bar(x, insight.df["recall_big_winner"].astype(float), width, label="Recall big_winner")
    ax.bar(x + width, insight.df["recall_big_loser"].astype(float), width, label="Recall big_loser")
    ax.set_xticks(x)
    ax.set_xticklabels(policies)
    ax.set_title("Baseline vs LightGBM (out-of-fold)")
    ax.set_ylabel("Score (0-1)")
    ax.legend(fontsize=8)
    name = "09_baseline_vs_gbm.png"
    return {name: _save(plt, fig, output_dir, name)}
