"""Pure-data analytics helpers for the learning pipeline.

Each ``compute_*`` function takes a DataFrame (or a model result) and returns
a ``dict``/``pandas.DataFrame`` suitable for both PNG rendering
(``src.learning.visualisations``) and JSON serialisation
(``data/learning/reports/<run>/metrics.json``).

The helpers are intentionally framework-light: they import pandas/numpy only,
so the dashboard and the notebook can both call them without pulling matplotlib
or lightgbm.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from src.learning.spec import get_default_spec


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class InsightTable:
    """Convenience container with both the DataFrame and a JSON-safe dict."""

    df: pd.DataFrame
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.df.to_dict(orient="records"),
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Label distribution
# ---------------------------------------------------------------------------


def compute_label_distribution(df: pd.DataFrame, label_col: str = "label_3class") -> InsightTable:
    """Counts + percentages for the 3-class target (v6 bands; legacy ``neutral`` rows tolerated)."""
    if df.empty or label_col not in df.columns:
        return InsightTable(pd.DataFrame(columns=[label_col, "count", "pct"]), {"total": 0})
    counts = df[label_col].fillna("missing").value_counts(dropna=False)
    total = int(counts.sum())
    out = pd.DataFrame(
        {
            label_col: counts.index.astype(str),
            "count": counts.values.astype(int),
            "pct": (counts.values / total * 100.0).astype(float),
        }
    )
    return InsightTable(
        df=out,
        summary={
            "total": total,
            "label_priors": {
                str(row[label_col]): float(row["pct"]) / 100.0 for _, row in out.iterrows()
            },
        },
    )


# ---------------------------------------------------------------------------
# Conviction calibration
# ---------------------------------------------------------------------------


def compute_conviction_calibration(
    df: pd.DataFrame,
    *,
    conviction_col: str = "conviction",
    label_col: str = "label_3class",
    bin_edges: Sequence[float] = (0.0, 50.0, 60.0, 70.0, 80.0, 100.001),
) -> InsightTable:
    """Empirical predicted-vs-realized win rate per conviction bin.

    The mean predicted win rate per bin is the calibration target: if the
    isotonic curve says "70 conviction -> 55% win rate" then the empirical
    win rate in that bin should also be ~55%. The gap is what the
    calibrator corrects.
    """
    if (
        df.empty
        or conviction_col not in df.columns
        or label_col not in df.columns
    ):
        return InsightTable(pd.DataFrame(), {"n_rows": 0})
    work = df[[conviction_col, label_col]].copy()
    work = work.dropna(subset=[conviction_col, label_col])
    if work.empty:
        return InsightTable(pd.DataFrame(), {"n_rows": 0})
    work["bin"] = pd.cut(
        work[conviction_col].astype(float),
        bins=list(bin_edges),
        right=False,
        include_lowest=True,
    )
    work["win"] = (work[label_col].astype(str) == "big_winner").astype(int)

    rows: list[dict[str, Any]] = []
    monotonic = True
    last_rate: float | None = None
    for label, group in work.groupby("bin", observed=False):
        count = int(len(group))
        if count == 0:
            rows.append(
                {
                    "bin": str(label),
                    "count": 0,
                    "mean_conviction": math.nan,
                    "empirical_win_rate": math.nan,
                }
            )
            continue
        empirical = float(group["win"].mean())
        mean_conv = float(group[conviction_col].mean())
        if last_rate is not None and empirical < last_rate - 1e-9:
            monotonic = False
        last_rate = empirical
        rows.append(
            {
                "bin": str(label),
                "count": count,
                "mean_conviction": mean_conv,
                "empirical_win_rate": empirical,
            }
        )
    return InsightTable(
        df=pd.DataFrame(rows),
        summary={
            "n_rows": int(work.shape[0]),
            "monotonic": bool(monotonic),
            "global_win_rate": float(work["win"].mean()),
        },
    )


# ---------------------------------------------------------------------------
# Realized P&L distribution
# ---------------------------------------------------------------------------


def compute_realized_pnl_buckets(
    df: pd.DataFrame,
    *,
    pnl_col: str = "realized_pnl_pct",
    edges: Sequence[float] = (-100.0, -25.0, -10.0, -3.0, 0.0, 3.0, 10.0, 25.0, 100.0),
) -> InsightTable:
    """Histogram + cumulative distribution of realized PnL on closed trades."""
    if df.empty or pnl_col not in df.columns:
        return InsightTable(pd.DataFrame(), {"n_closed": 0})
    closed = df.dropna(subset=[pnl_col]).copy()
    if closed.empty:
        return InsightTable(pd.DataFrame(), {"n_closed": 0})
    closed["bucket"] = pd.cut(closed[pnl_col].astype(float), bins=list(edges), right=False)
    grouped = closed.groupby("bucket", observed=False).size().rename("count").reset_index()
    grouped["bucket"] = grouped["bucket"].astype(str)
    total = int(grouped["count"].sum()) or 1
    grouped["pct"] = grouped["count"].astype(int) / total * 100.0
    grouped["cumulative_pct"] = grouped["pct"].cumsum()

    values = closed[pnl_col].astype(float)
    cfg = get_default_spec().labels
    if "label_3class" in closed.columns:
        labels = closed["label_3class"].astype(str)
        big_winner_pct = float((labels == "big_winner").mean() * 100.0)
        big_loser_pct = float((labels == "big_loser").mean() * 100.0)
    else:
        holding = closed.get("realized_holding_days", pd.Series([30.0] * len(closed))).astype(float).clip(lower=1.0)
        gpd = values / holding
        big_winner_pct = float((gpd >= cfg.success_min_profit_per_day_pct).mean() * 100.0)
        big_loser_pct = float((gpd < cfg.stall_min_gain_per_day_pct).mean() * 100.0)
    summary = {
        "n_closed": int(closed.shape[0]),
        "mean_pnl_pct": float(values.mean()),
        "median_pnl_pct": float(values.median()),
        "win_rate_pct": float((values > 0).mean() * 100.0),
        "big_winner_pct": big_winner_pct,
        "big_loser_pct": big_loser_pct,
    }
    return InsightTable(df=grouped, summary=summary)


# ---------------------------------------------------------------------------
# Horizon (holding-day) distribution per label
# ---------------------------------------------------------------------------


def compute_horizon_distribution(
    df: pd.DataFrame,
    *,
    holding_col: str = "realized_holding_days",
    label_col: str = "label_3class",
) -> InsightTable:
    """Per-label mean / median / std of holding days for closed trades."""
    if df.empty or holding_col not in df.columns or label_col not in df.columns:
        return InsightTable(pd.DataFrame(), {"n_closed": 0})
    closed = df.dropna(subset=[holding_col]).copy()
    if closed.empty:
        return InsightTable(pd.DataFrame(), {"n_closed": 0})
    grouped = (
        closed.groupby(label_col)[holding_col]
        .agg(["count", "mean", "median", "std"])
        .reset_index()
        .rename(columns={label_col: "label"})
    )
    grouped["count"] = grouped["count"].astype(int)
    for c in ("mean", "median", "std"):
        grouped[c] = grouped[c].astype(float).fillna(0.0)
    return InsightTable(
        df=grouped,
        summary={"n_closed": int(closed.shape[0])},
    )


# ---------------------------------------------------------------------------
# Macro regime outcomes
# ---------------------------------------------------------------------------


def compute_macro_regime_outcomes(
    df: pd.DataFrame,
    *,
    regime_col: str = "macro_regime",
    label_col: str = "label_3class",
) -> InsightTable:
    """Win-rate breakdown by RISK_ON / NEUTRAL / RISK_OFF macro regime."""
    if df.empty or regime_col not in df.columns or label_col not in df.columns:
        return InsightTable(pd.DataFrame(), {"n_rows": 0})
    work = df.copy()
    work[regime_col] = work[regime_col].fillna("UNKNOWN").astype(str)
    work["win"] = (work[label_col].astype(str) == "big_winner").astype(int)
    work["loss"] = (work[label_col].astype(str) == "big_loser").astype(int)
    grouped = (
        work.groupby(regime_col)
        .agg(
            n=("win", "size"),
            win_rate=("win", "mean"),
            loss_rate=("loss", "mean"),
        )
        .reset_index()
        .rename(columns={regime_col: "regime"})
    )
    grouped["n"] = grouped["n"].astype(int)
    grouped["win_rate"] = grouped["win_rate"].astype(float)
    grouped["loss_rate"] = grouped["loss_rate"].astype(float)
    grouped = grouped.sort_values("regime").reset_index(drop=True)
    return InsightTable(
        df=grouped,
        summary={
            "n_rows": int(work.shape[0]),
            "global_win_rate": float(work["win"].mean()),
        },
    )


def compute_guidance_sector_outcomes(
    df: pd.DataFrame,
    *,
    label_col: str = "label_3class",
    guidance_col: str = "guidance_sector_label",
) -> InsightTable:
    """Win/loss breakdown by guidance sector label (favored/neutral/avoid)."""
    if df.empty or guidance_col not in df.columns or label_col not in df.columns:
        return InsightTable(pd.DataFrame(), {"n_rows": 0})
    work = df.copy()
    work[guidance_col] = work[guidance_col].fillna("UNKNOWN").astype(str)
    work["win"] = (work[label_col].astype(str) == "big_winner").astype(int)
    work["loss"] = (work[label_col].astype(str) == "big_loser").astype(int)
    grouped = (
        work.groupby(guidance_col)
        .agg(n=("win", "size"), win_rate=("win", "mean"), loss_rate=("loss", "mean"))
        .reset_index()
        .rename(columns={guidance_col: "guidance_label"})
    )
    grouped["n"] = grouped["n"].astype(int)
    return InsightTable(
        df=grouped,
        summary={"n_rows": int(work.shape[0]), "global_win_rate": float(work["win"].mean())},
    )


def compute_news_sentiment_outcomes(
    df: pd.DataFrame,
    *,
    score_col: str = "news_sentiment_score",
    label_col: str = "label_3class",
    n_bins: int = 5,
) -> InsightTable:
    """Bad-rate by news sentiment score decile."""
    if df.empty or score_col not in df.columns or label_col not in df.columns:
        return InsightTable(pd.DataFrame(), {"n_rows": 0})
    work = df[[score_col, label_col]].dropna()
    if work.empty:
        return InsightTable(pd.DataFrame(), {"n_rows": 0})
    work["bad"] = work[label_col].astype(str).isin({"big_loser", "stall"}).astype(int)
    try:
        work["decile"] = pd.qcut(work[score_col].astype(float), q=n_bins, duplicates="drop")
    except ValueError:
        work["decile"] = pd.cut(work[score_col].astype(float), bins=n_bins)
    grouped = (
        work.groupby("decile", observed=False)
        .agg(n=("bad", "size"), bad_rate=("bad", "mean"), mean_score=(score_col, "mean"))
        .reset_index()
    )
    grouped["decile"] = grouped["decile"].astype(str)
    grouped["n"] = grouped["n"].astype(int)
    return InsightTable(df=grouped, summary={"n_rows": int(work.shape[0])})


def compute_screening_delta_outcomes(
    df: pd.DataFrame,
    *,
    delta_col: str = "guidance_candidate_delta",
    label_col: str = "label_3class",
) -> InsightTable:
    """Outcome rates when guidance shrank vs expanded the candidate universe."""
    if df.empty or delta_col not in df.columns or label_col not in df.columns:
        return InsightTable(pd.DataFrame(), {"n_rows": 0})
    work = df.copy()
    work["bad"] = work[label_col].astype(str).isin({"big_loser", "stall"}).astype(int)
    work["win"] = (work[label_col].astype(str) == "big_winner").astype(int)
    work["screening_effect"] = np.where(
        work[delta_col].fillna(0) < 0,
        "shrunk",
        np.where(work[delta_col].fillna(0) > 0, "expanded", "unchanged"),
    )
    grouped = (
        work.groupby("screening_effect")
        .agg(n=("bad", "size"), bad_rate=("bad", "mean"), win_rate=("win", "mean"))
        .reset_index()
    )
    grouped["n"] = grouped["n"].astype(int)
    return InsightTable(df=grouped, summary={"n_rows": int(work.shape[0])})


# ---------------------------------------------------------------------------
# Feature importance
# ---------------------------------------------------------------------------


def compute_feature_importance(
    importance_map: dict[str, float] | None,
    *,
    top_n: int = 20,
) -> InsightTable:
    """Top-N features by mean gain (already normalised in GBMTrainingResult)."""
    if not importance_map:
        return InsightTable(pd.DataFrame(columns=["feature", "relative_gain"]), {"top_n": 0})
    items = sorted(importance_map.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    out = pd.DataFrame(items, columns=["feature", "relative_gain"])
    out["relative_gain"] = out["relative_gain"].astype(float)
    return InsightTable(
        df=out,
        summary={
            "top_n": int(len(out)),
            "top_feature": str(out.iloc[0]["feature"]) if len(out) else None,
            "top_gain": float(out.iloc[0]["relative_gain"]) if len(out) else 0.0,
            "cumulative_gain_top10": float(out.head(10)["relative_gain"].sum()),
        },
    )


# ---------------------------------------------------------------------------
# Baseline lift
# ---------------------------------------------------------------------------


def compute_baseline_lift(
    df: pd.DataFrame,
    *,
    label_col: str = "label_3class",
    conviction_col: str = "conviction",
    gbm_aggregate_metrics: dict[str, Any] | None = None,
    gbm_oof: pd.DataFrame | None = None,
) -> InsightTable:
    """Rank LightGBM against the trivial / conviction-only baselines.

    Three numbers per metric:

    - ``majority`` — always predict the modal class. Big-loser recall is 0.
    - ``conviction_only`` — bin conviction into 5 buckets, predict the
      per-bin modal class. This is what we had pre-calibrator.
    - ``gbm`` — out-of-fold LightGBM accuracy / macro-F1 / per-class recall.
    """
    rows: list[dict[str, Any]] = []
    if df.empty or label_col not in df.columns:
        return InsightTable(pd.DataFrame(rows), {"n_rows": 0})

    labels = df[label_col].astype(str)
    valid = labels.notna() & labels.isin(["big_winner", "stall", "big_loser", "neutral"])
    if not valid.any():
        return InsightTable(pd.DataFrame(rows), {"n_rows": 0})

    classes = ["big_loser", "stall", "big_winner"]

    # Majority baseline.
    majority_class = labels[valid].mode().iat[0]
    maj_preds = np.array([majority_class] * int(valid.sum()))
    maj_truth = labels[valid].to_numpy()
    rows.append(_score_row("majority", maj_truth, maj_preds, classes))

    # Conviction-only baseline (per-bucket modal class).
    if conviction_col in df.columns:
        work = df[[conviction_col, label_col]].dropna()
        if not work.empty:
            work["bin"] = pd.cut(
                work[conviction_col].astype(float),
                bins=[0, 50, 60, 70, 80, 100.001],
                right=False,
                include_lowest=True,
            )
            modes = (
                work.groupby("bin", observed=False)[label_col]
                .agg(lambda s: s.mode().iat[0] if not s.empty and not s.mode().empty else majority_class)
            )
            preds = work["bin"].map(modes).fillna(majority_class).to_numpy()
            rows.append(_score_row("conviction_only", work[label_col].astype(str).to_numpy(), preds, classes))

    # GBM out-of-fold.
    if gbm_oof is not None and not gbm_oof.empty and "label_3class" in gbm_oof.columns:
        prob_cols = [c for c in gbm_oof.columns if c.startswith("prob_")]
        if prob_cols:
            argmax = gbm_oof[prob_cols].to_numpy().argmax(axis=1)
            pred_labels = np.array(
                [prob_cols[i].replace("prob_", "") for i in argmax]
            )
            rows.append(
                _score_row(
                    "gbm_oof",
                    gbm_oof["label_3class"].astype(str).to_numpy(),
                    pred_labels,
                    classes,
                )
            )
    elif gbm_aggregate_metrics:
        # Fall back to aggregate metrics if OOF frame is unavailable.
        per_class = gbm_aggregate_metrics.get("per_class_recall") or {}
        macro_f1 = (
            float(np.mean(list(per_class.values()))) if per_class else float(gbm_aggregate_metrics.get("accuracy", 0.0))
        )
        rows.append(
            {
                "policy": "gbm_oof",
                "accuracy": float(gbm_aggregate_metrics.get("accuracy", 0.0)),
                "macro_f1": macro_f1,
                "recall_big_winner": float(per_class.get("big_winner", 0.0)),
                "recall_big_loser": float(per_class.get("big_loser", 0.0)),
            }
        )

    out = pd.DataFrame(rows)
    summary: dict[str, Any] = {"n_rows": int(valid.sum())}
    if not out.empty and "gbm_oof" in set(out["policy"]):
        gbm_row = out[out["policy"] == "gbm_oof"].iloc[0]
        for policy in ("majority", "conviction_only"):
            if policy in set(out["policy"]):
                base = out[out["policy"] == policy].iloc[0]
                summary[f"lift_macro_f1_vs_{policy}"] = float(gbm_row["macro_f1"] - base["macro_f1"])
                summary[f"lift_recall_big_loser_vs_{policy}"] = float(
                    gbm_row["recall_big_loser"] - base["recall_big_loser"]
                )
    return InsightTable(df=out, summary=summary)


def _score_row(
    policy: str,
    truth: np.ndarray,
    preds: np.ndarray,
    classes: Sequence[str],
) -> dict[str, Any]:
    accuracy = float((truth == preds).mean()) if len(truth) else 0.0
    recalls: dict[str, float] = {}
    for cls in classes:
        mask = truth == cls
        recalls[cls] = float((preds[mask] == cls).mean()) if mask.any() else 0.0
    macro_f1 = float(np.mean(list(recalls.values()))) if recalls else 0.0
    return {
        "policy": policy,
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "recall_big_winner": float(recalls.get("big_winner", 0.0)),
        "recall_big_loser": float(recalls.get("big_loser", 0.0)),
    }


# ---------------------------------------------------------------------------
# Conviction vs realized PnL scatter helpers
# ---------------------------------------------------------------------------


def compute_conviction_vs_pnl_scatter(
    df: pd.DataFrame,
    *,
    conviction_col: str = "conviction",
    pnl_col: str = "realized_pnl_pct",
    max_points: int = 2000,
) -> InsightTable:
    """Sample of closed trades for a conviction vs realized-PnL scatter plot."""
    if df.empty or conviction_col not in df.columns or pnl_col not in df.columns:
        return InsightTable(pd.DataFrame(), {"n_closed": 0})
    work = df[[conviction_col, pnl_col]].dropna()
    if work.empty:
        return InsightTable(pd.DataFrame(), {"n_closed": 0})
    if len(work) > max_points:
        work = work.sample(n=max_points, random_state=42)
    correlation = float(work[conviction_col].astype(float).corr(work[pnl_col].astype(float)))
    return InsightTable(
        df=work.rename(columns={conviction_col: "conviction", pnl_col: "realized_pnl_pct"}).reset_index(drop=True),
        summary={
            "n_closed": int(work.shape[0]),
            "pearson_correlation": correlation if not math.isnan(correlation) else 0.0,
        },
    )
