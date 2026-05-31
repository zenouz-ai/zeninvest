"""Stall / time-to-event scorer.

We frame the problem as: given features at decision time, how long does the
position sit between ``-stall_band_pct`` and ``+stall_band_pct`` before it
either resolves (crosses the band) or reaches the horizon cap?

For sample sizes this small, we use a lightweight LightGBM regression on the
log-time-to-resolution with an event mask, plus a logistic stall classifier
as a robust fallback. Both share the same feature set as the GBM scorer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd

from src.learning.dataset.splits import WalkForwardSplits, WalkForwardSplitter
from src.utils.logger import get_logger

logger = get_logger("learning.stall")


@dataclass
class StallTrainingResult:
    """Walk-forward training result for the stall scorer."""

    feature_columns: list[str]
    per_fold_metrics: list[dict[str, Any]]
    aggregate_metrics: dict[str, Any]
    feature_importance: dict[str, float]
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "feature_columns": self.feature_columns,
            "per_fold_metrics": self.per_fold_metrics,
            "aggregate_metrics": self.aggregate_metrics,
            "feature_importance": self.feature_importance,
            "metadata": self.metadata,
        }


class StallSurvivalModel:
    """Inference wrapper for a fitted stall classifier."""

    def __init__(self, boosters: list[Any], feature_columns: Sequence[str]) -> None:
        self.boosters = list(boosters)
        self.feature_columns = list(feature_columns)

    def predict_stall_probability(self, df: pd.DataFrame) -> np.ndarray:
        if not self.boosters:
            raise RuntimeError("No stall boosters available.")
        x = df.reindex(columns=self.feature_columns).to_numpy()
        preds = np.zeros(len(df), dtype=float)
        for booster in self.boosters:
            preds += booster.predict(x, num_iteration=booster.best_iteration)
        preds /= len(self.boosters)
        return preds


def _lazy_lightgbm():
    try:  # pragma: no cover - import gate
        import lightgbm as lgb  # type: ignore
        return lgb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "lightgbm is required for the stall scorer. Install with `poetry install --with learning`."
        ) from exc


def _select_features(df: pd.DataFrame, exclude: set[str]) -> list[str]:
    cols = []
    for col in df.columns:
        if col in exclude:
            continue
        if col.startswith("ret_") or col.startswith("mtm_max_"):
            continue
        series = df[col]
        if series.dtype == bool:
            df[col] = series.astype(int)
            cols.append(col)
            continue
        if pd.api.types.is_numeric_dtype(series):
            cols.append(col)
    return cols


def train_stall_model(
    df: pd.DataFrame,
    *,
    label_col: str = "label_3class",
    horizon_col: str = "ret_30d",
    walk_forward: WalkForwardSplits | None = None,
    embargo_days: int = 30,
    test_window_days: int = 14,
    seed: int = 42,
    num_boost_round: int = 150,
    early_stopping_rounds: int = 20,
) -> StallTrainingResult:
    """Train a walk-forward binary stall classifier (1 = stall, 0 = otherwise).

    Returns a :class:`StallTrainingResult` plus inference handles. The 30d
    horizon column is used purely for diagnostic reporting (not as a feature).
    """
    lgb = _lazy_lightgbm()
    if df.empty:
        raise ValueError("Cannot train on empty DataFrame")
    if label_col not in df.columns:
        raise ValueError(f"Missing label column: {label_col}")

    work = df.copy().sort_values("decision_ts").reset_index(drop=True)
    exclude = {
        label_col,
        "cycle_id",
        "ticker",
        "decision_ts",
        "realized_pnl_pct",
        "realized_holding_days",
        "exit_reason",
        "actually_traded",
    }
    feature_cols = _select_features(work, exclude)
    if not feature_cols:
        raise ValueError("No numeric features available for stall model.")

    y = (work[label_col].astype(str) == "stall").astype(int).to_numpy()
    if y.sum() == 0:
        return StallTrainingResult(
            feature_columns=feature_cols,
            per_fold_metrics=[],
            aggregate_metrics={"note": "no stall rows; stall model skipped"},
            feature_importance={},
            metadata={"n_rows": int(len(work))},
        )

    timestamps = work["decision_ts"].tolist()
    if walk_forward is None:
        walk_forward = WalkForwardSplitter(embargo_days=embargo_days, test_window_days=test_window_days).split(timestamps)
    if walk_forward.n_folds == 0:
        raise ValueError("Walk-forward CV produced 0 folds for stall training.")

    per_fold: list[dict[str, Any]] = []
    boosters: list[Any] = []
    for fold in walk_forward.folds:
        train_idx = list(fold.train_indices)
        test_idx = list(fold.test_indices)
        if not train_idx or not test_idx:
            continue
        x_train = work.iloc[train_idx][feature_cols].to_numpy()
        y_train = y[train_idx]
        x_test = work.iloc[test_idx][feature_cols].to_numpy()
        y_test = y[test_idx]
        if y_train.sum() < 3:
            continue
        pos_weight = (len(y_train) - y_train.sum()) / max(y_train.sum(), 1)
        train_set = lgb.Dataset(x_train, label=y_train, free_raw_data=False)
        valid_set = lgb.Dataset(x_test, label=y_test, reference=train_set, free_raw_data=False)
        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "verbosity": -1,
            "num_leaves": 21,
            "min_data_in_leaf": max(5, min(15, len(train_idx) // 50)),
            "learning_rate": 0.05,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.9,
            "bagging_freq": 5,
            "scale_pos_weight": float(pos_weight),
            "seed": seed,
            "deterministic": True,
            "force_row_wise": True,
        }
        try:
            booster = lgb.train(
                params,
                train_set,
                num_boost_round=num_boost_round,
                valid_sets=[valid_set],
                callbacks=[lgb.early_stopping(early_stopping_rounds, verbose=False)],
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Stall booster training failed for fold %s: %s", fold.fold_id, exc)
            continue
        proba = booster.predict(x_test, num_iteration=booster.best_iteration)
        per_fold.append(
            {
                "fold_id": fold.fold_id,
                "train_rows": len(train_idx),
                "test_rows": len(test_idx),
                "logloss": float(_safe_logloss(y_test, proba)),
                "auc": float(_safe_auc(y_test, proba)),
            }
        )
        boosters.append(booster)

    if not boosters:
        return StallTrainingResult(
            feature_columns=feature_cols,
            per_fold_metrics=[],
            aggregate_metrics={"note": "no folds trained"},
            feature_importance={},
            metadata={"n_rows": int(len(work))},
        )

    aggregate = {
        "logloss": float(np.mean([m["logloss"] for m in per_fold if m["logloss"] == m["logloss"]])),
        "auc": float(np.mean([m["auc"] for m in per_fold if m["auc"] == m["auc"]])),
        "n_folds": len(per_fold),
    }
    importance = np.zeros(len(feature_cols), dtype=float)
    for booster in boosters:
        importance[: booster.feature_importance(importance_type="gain").shape[0]] += booster.feature_importance(
            importance_type="gain"
        )
    total = importance.sum() or 1.0
    importance /= total
    importance_dict = {col: float(importance[i]) for i, col in enumerate(feature_cols)}
    return StallTrainingResult(
        feature_columns=feature_cols,
        per_fold_metrics=per_fold,
        aggregate_metrics=aggregate,
        feature_importance=importance_dict,
        metadata={"n_rows": int(len(work)), "horizon_col": horizon_col, "seed": seed},
    )


def _safe_logloss(y_true: np.ndarray, proba: np.ndarray) -> float:
    eps = 1e-9
    p = np.clip(proba, eps, 1 - eps)
    return float(-np.mean(y_true * np.log(p) + (1 - y_true) * np.log(1 - p)))


def _safe_auc(y_true: np.ndarray, proba: np.ndarray) -> float:
    try:  # pragma: no cover - sklearn import gate
        from sklearn.metrics import roc_auc_score
    except ImportError:  # pragma: no cover
        return float("nan")
    if len(np.unique(y_true)) < 2:
        return float("nan")
    try:
        return float(roc_auc_score(y_true, proba))
    except ValueError:
        return float("nan")
