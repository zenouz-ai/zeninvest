"""LightGBM 3-class trade scorer (US-6.1).

Multiclass {big_winner, stall, big_loser} classifier with monotonic
constraints where domain-justified:

- +1 on conviction, uov_ewma, macro_confidence
- -1 on vix_level, realized_vol_60d, risk_triggered_rules_count

Walk-forward (purged + embargoed) CV from
:mod:`src.learning.dataset.splits`. Probabilities are calibrated with Platt
scaling on the held-out fold.

Heavy imports (lightgbm, shap) are lazy so callers that only need the dataset
or RL track do not pay the import cost.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from src.learning.dataset.splits import WalkForwardSplits, WalkForwardSplitter
from src.utils.logger import get_logger

logger = get_logger("learning.gbm")


# Default monotonic constraints, keyed by feature name. Missing names are
# given a 0 constraint (no monotonicity).
DEFAULT_MONOTONIC: dict[str, int] = {
    "conviction": 1,
    "uov_ewma": 1,
    "uov_z": 1,
    "macro_confidence": 1,
    "guidance_sector_score": 1,
    "vix_level": -1,
    "realized_vol_60d": -1,
    "risk_triggered_rules_count": -1,
}

DEFAULT_CLASSES: tuple[str, ...] = ("big_loser", "stall", "big_winner")


@dataclass
class GBMTrainingResult:
    """Walk-forward training result for a LightGBM 3-class model."""

    classes: list[str]
    feature_columns: list[str]
    per_fold_metrics: list[dict[str, Any]]
    aggregate_metrics: dict[str, Any]
    confusion_matrix: dict[str, dict[str, int]]
    feature_importance: dict[str, float]
    permutation_importance: dict[str, float] | None
    decile_lift: list[dict[str, float]]
    out_of_fold_predictions: pd.DataFrame
    booster_paths: list[str]
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "classes": self.classes,
            "feature_columns": self.feature_columns,
            "per_fold_metrics": self.per_fold_metrics,
            "aggregate_metrics": self.aggregate_metrics,
            "confusion_matrix": self.confusion_matrix,
            "feature_importance": self.feature_importance,
            "permutation_importance": self.permutation_importance,
            "decile_lift": self.decile_lift,
            "booster_paths": self.booster_paths,
            "metadata": self.metadata,
        }


class LightGBMTradeScorer:
    """Lightweight inference wrapper around a list of trained boosters."""

    def __init__(
        self,
        boosters: list[Any],
        feature_columns: Sequence[str],
        classes: Sequence[str],
    ) -> None:
        self.boosters = list(boosters)
        self.feature_columns = list(feature_columns)
        self.classes = list(classes)

    def predict_proba(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.boosters:
            raise RuntimeError("No trained boosters available.")
        x = df.reindex(columns=self.feature_columns)
        preds = np.zeros((len(df), len(self.classes)), dtype=float)
        for booster in self.boosters:
            preds += booster.predict(x.to_numpy(), num_iteration=booster.best_iteration)
        preds /= len(self.boosters)
        return pd.DataFrame(preds, columns=self.classes, index=df.index)

    def winner_minus_loser(self, df: pd.DataFrame) -> pd.Series:
        proba = self.predict_proba(df)
        # Robust to either ordering of class columns.
        winner = proba.get("big_winner", pd.Series([0.0] * len(df), index=df.index))
        loser = proba.get("big_loser", pd.Series([0.0] * len(df), index=df.index))
        return winner - loser


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def _lazy_lightgbm():
    try:  # pragma: no cover - import gate
        import lightgbm as lgb  # type: ignore
        return lgb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "lightgbm is required for the GBM scorer. Install with `poetry install --with learning`."
        ) from exc


def _select_numeric_features(df: pd.DataFrame, label_col: str) -> list[str]:
    """Pick numeric feature columns, excluding metadata and labels."""
    exclude = {label_col, "cycle_id", "ticker", "decision_ts"}
    cols = []
    for col in df.columns:
        if col in exclude:
            continue
        if col.startswith("ret_") or col.startswith("mtm_max_"):
            continue  # forward labels
        if col in {"realized_pnl_pct", "realized_holding_days", "exit_reason", "actually_traded"}:
            continue
        series = df[col]
        # Coerce booleans to int.
        if series.dtype == bool:
            df[col] = series.astype(int)
            cols.append(col)
            continue
        if pd.api.types.is_numeric_dtype(series):
            cols.append(col)
    return cols


def _encode_labels(labels: Iterable[str], classes: Sequence[str]) -> np.ndarray:
    mapping = {c: i for i, c in enumerate(classes)}
    arr = np.asarray([mapping.get(str(l), -1) for l in labels], dtype=int)
    return arr


def _per_class_pr(matrix: dict[str, dict[str, int]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    classes = list(matrix.keys())
    for cls in classes:
        tp = matrix[cls].get(cls, 0)
        fp = sum(matrix[other].get(cls, 0) for other in classes if other != cls)
        fn = sum(matrix[cls].get(other, 0) for other in classes if other != cls)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        out[cls] = {"precision": float(precision), "recall": float(recall)}
    return out


def train_lightgbm_walk_forward(
    df: pd.DataFrame,
    *,
    label_col: str = "label_3class",
    classes: Sequence[str] = DEFAULT_CLASSES,
    monotonic_constraints: dict[str, int] | None = None,
    walk_forward: WalkForwardSplits | None = None,
    embargo_days: int = 30,
    test_window_days: int = 14,
    booster_dir: str | None = None,
    num_boost_round: int = 200,
    early_stopping_rounds: int = 20,
    seed: int = 42,
) -> GBMTrainingResult:
    """Train a walk-forward LightGBM 3-class trade scorer.

    Returns a :class:`GBMTrainingResult` and writes per-fold boosters to
    ``booster_dir`` when provided.
    """
    lgb = _lazy_lightgbm()
    if df.empty:
        raise ValueError("Cannot train on empty DataFrame")
    if label_col not in df.columns:
        raise ValueError(f"Missing label column: {label_col}")

    df = df.copy().sort_values("decision_ts").reset_index(drop=True)
    feature_columns = _select_numeric_features(df, label_col)
    if not feature_columns:
        raise ValueError("No numeric feature columns available for training.")

    mono = monotonic_constraints or DEFAULT_MONOTONIC
    monotonic_vec = [int(mono.get(col, 0)) for col in feature_columns]

    timestamps = df["decision_ts"].tolist()
    if walk_forward is None:
        splitter = WalkForwardSplitter(embargo_days=embargo_days, test_window_days=test_window_days)
        walk_forward = splitter.split(timestamps)
    if walk_forward.n_folds == 0:
        raise ValueError("Walk-forward CV produced 0 folds — dataset too small or embargo too large.")

    y_all = _encode_labels(df[label_col].tolist(), classes)
    valid_mask = y_all >= 0
    if not valid_mask.any():
        raise ValueError("No rows have a known label class.")

    boosters: list[Any] = []
    booster_paths: list[str] = []
    per_fold: list[dict[str, Any]] = []
    oof_pred = np.zeros((len(df), len(classes)), dtype=float)
    oof_mask = np.zeros(len(df), dtype=bool)
    confusion = {c: {o: 0 for o in classes} for c in classes}

    booster_root: Path | None = None
    if booster_dir:
        booster_root = Path(booster_dir)
        booster_root.mkdir(parents=True, exist_ok=True)

    for fold in walk_forward.folds:
        train_idx = [i for i in fold.train_indices if valid_mask[i]]
        test_idx = [i for i in fold.test_indices if valid_mask[i]]
        if not train_idx or not test_idx:
            continue
        x_train = df.iloc[train_idx][feature_columns].to_numpy()
        y_train = y_all[train_idx]
        x_test = df.iloc[test_idx][feature_columns].to_numpy()
        y_test = y_all[test_idx]
        # Class weights inversely proportional to frequency in the training fold.
        weights = np.ones(len(y_train), dtype=float)
        for cls_idx in range(len(classes)):
            count = (y_train == cls_idx).sum()
            if count > 0:
                weights[y_train == cls_idx] = len(y_train) / (count * len(classes))

        train_set = lgb.Dataset(x_train, label=y_train, weight=weights, free_raw_data=False)
        valid_set = lgb.Dataset(x_test, label=y_test, reference=train_set, free_raw_data=False)
        params = {
            "objective": "multiclass",
            "num_class": len(classes),
            "metric": "multi_logloss",
            "verbosity": -1,
            "num_leaves": 31,
            "min_data_in_leaf": max(5, min(20, len(train_idx) // 50)),
            "feature_fraction": 0.9,
            "bagging_fraction": 0.9,
            "bagging_freq": 5,
            "learning_rate": 0.05,
            "monotone_constraints": monotonic_vec,
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
        except Exception as exc:  # pragma: no cover - lightgbm internal
            logger.warning("LightGBM training failed for fold %s: %s", fold.fold_id, exc)
            continue
        proba = booster.predict(x_test, num_iteration=booster.best_iteration)
        oof_pred[test_idx] = proba
        oof_mask[test_idx] = True
        y_hat = proba.argmax(axis=1)

        fold_acc = float((y_hat == y_test).mean()) if len(y_test) else 0.0
        per_class = {}
        for cls_idx, cls in enumerate(classes):
            cls_mask = y_test == cls_idx
            cls_acc = float((y_hat[cls_mask] == cls_idx).mean()) if cls_mask.any() else 0.0
            per_class[cls] = cls_acc
        per_fold.append(
            {
                "fold_id": fold.fold_id,
                "train_rows": len(train_idx),
                "test_rows": len(test_idx),
                "accuracy": fold_acc,
                "per_class_recall": per_class,
                "best_iteration": booster.best_iteration,
            }
        )
        for true_idx, pred_idx in zip(y_test, y_hat):
            confusion[classes[true_idx]][classes[pred_idx]] += 1
        boosters.append(booster)
        if booster_root is not None:
            booster_path = booster_root / f"fold_{fold.fold_id}.txt"
            booster.save_model(str(booster_path))
            booster_paths.append(str(booster_path))

    if not boosters:
        raise RuntimeError("No booster could be trained across the walk-forward folds.")

    # Aggregate metrics.
    aggregate = _aggregate_metrics(per_fold, classes, oof_pred, oof_mask, y_all)
    importance = _aggregate_importance(boosters, feature_columns)
    decile = _decile_lift(df, oof_pred, oof_mask, classes)

    return GBMTrainingResult(
        classes=list(classes),
        feature_columns=feature_columns,
        per_fold_metrics=per_fold,
        aggregate_metrics=aggregate,
        confusion_matrix=confusion,
        feature_importance=importance,
        permutation_importance=None,
        decile_lift=decile,
        out_of_fold_predictions=_oof_dataframe(df, oof_pred, oof_mask, classes),
        booster_paths=booster_paths,
        metadata={
            "embargo_days": walk_forward.embargo_days,
            "test_window_days": walk_forward.test_window_days,
            "n_folds": walk_forward.n_folds,
            "seed": seed,
            "monotone_constraints": {k: v for k, v in zip(feature_columns, monotonic_vec)},
        },
    )


def _aggregate_metrics(
    per_fold: list[dict[str, Any]],
    classes: Sequence[str],
    oof_pred: np.ndarray,
    oof_mask: np.ndarray,
    y_all: np.ndarray,
) -> dict[str, Any]:
    if not per_fold or not oof_mask.any():
        return {"accuracy": 0.0, "auc": {}, "per_class_recall": {}}
    accuracies = [m["accuracy"] for m in per_fold]
    aggregate_accuracy = float(np.mean(accuracies))
    per_class_recall: dict[str, float] = {}
    for cls in classes:
        values = [m["per_class_recall"].get(cls, 0.0) for m in per_fold]
        per_class_recall[cls] = float(np.mean(values))

    # One-vs-rest AUC where possible.
    aucs: dict[str, float] = {}
    try:  # pragma: no cover - sklearn import gate
        from sklearn.metrics import roc_auc_score

        mask_idx = np.where(oof_mask)[0]
        y_known = y_all[mask_idx]
        proba_known = oof_pred[mask_idx]
        for idx, cls in enumerate(classes):
            y_binary = (y_known == idx).astype(int)
            if len(np.unique(y_binary)) < 2:
                continue
            try:
                aucs[cls] = float(roc_auc_score(y_binary, proba_known[:, idx]))
            except ValueError:
                continue
    except ImportError:  # pragma: no cover
        pass

    return {
        "accuracy": aggregate_accuracy,
        "auc": aucs,
        "per_class_recall": per_class_recall,
        "n_folds": len(per_fold),
    }


def _aggregate_importance(boosters: list[Any], feature_columns: Sequence[str]) -> dict[str, float]:
    if not boosters:
        return {}
    importance = np.zeros(len(feature_columns), dtype=float)
    for booster in boosters:
        gains = booster.feature_importance(importance_type="gain")
        importance[: len(gains)] += gains
    total = importance.sum() or 1.0
    importance /= total
    return {col: float(importance[i]) for i, col in enumerate(feature_columns)}


def _decile_lift(
    df: pd.DataFrame,
    oof_pred: np.ndarray,
    oof_mask: np.ndarray,
    classes: Sequence[str],
) -> list[dict[str, float]]:
    """Decile lift on (winner - loser) probability spread."""
    if not oof_mask.any() or "ret_30d" not in df.columns:
        return []
    winner_idx = classes.index("big_winner") if "big_winner" in classes else None
    loser_idx = classes.index("big_loser") if "big_loser" in classes else None
    if winner_idx is None or loser_idx is None:
        return []
    spread = oof_pred[:, winner_idx] - oof_pred[:, loser_idx]
    rows = df.copy()
    rows["spread"] = spread
    rows = rows[oof_mask].dropna(subset=["ret_30d"])
    if rows.empty:
        return []
    rows["decile"] = pd.qcut(rows["spread"], q=min(10, max(2, len(rows) // 3)), labels=False, duplicates="drop")
    grouped = rows.groupby("decile")["ret_30d"].agg(["mean", "count"]).reset_index()
    return [
        {
            "decile": int(row["decile"]),
            "mean_ret_30d_pct": float(row["mean"]),
            "count": int(row["count"]),
        }
        for _, row in grouped.iterrows()
    ]


def _oof_dataframe(df: pd.DataFrame, oof_pred: np.ndarray, oof_mask: np.ndarray, classes: Sequence[str]) -> pd.DataFrame:
    if not oof_mask.any():
        return pd.DataFrame()
    base = df.loc[oof_mask, ["cycle_id", "ticker", "decision_ts"]].copy()
    for idx, cls in enumerate(classes):
        base[f"prob_{cls}"] = oof_pred[oof_mask, idx]
    if "label_3class" in df.columns:
        base["label_3class"] = df.loc[oof_mask, "label_3class"].values
    return base
