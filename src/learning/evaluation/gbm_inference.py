"""Shared GBM probability inference for counterfactual and live shadow scoring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.learning.registry import active_dataset_version, resolve_champion_run
from src.utils.logger import get_logger

logger = get_logger("learning.evaluation.gbm_inference")

DEFAULT_CLASSES = ("big_loser", "stall", "big_winner")


def project_root() -> Path:
    import os

    override = os.environ.get("INVESTMENT_AGENT_LEARNING_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3]


def latest_gbm_artifact(
    root: Path | None = None,
    *,
    dataset_version: str | None = None,
) -> tuple[str | None, list[str] | None, list[str]]:
    from src.data.database import get_session

    root = root or project_root()
    session = get_session()
    try:
        row = resolve_champion_run(
            session,
            dataset_version=dataset_version or active_dataset_version(),
        )
        if row is None:
            return None, None, list(DEFAULT_CLASSES)
        metrics_path = root / "data" / "learning" / "reports" / row.run_id / "metrics.json"
        if not metrics_path.exists():
            return None, None, list(DEFAULT_CLASSES)
        metrics = json.loads(metrics_path.read_text())
        gbm = metrics.get("gbm") or {}
        return row.run_id, gbm.get("feature_columns"), gbm.get("classes") or list(DEFAULT_CLASSES)
    finally:
        session.close()


def heuristic_probs(conviction: float) -> dict[str, float]:
    conv = float(conviction)
    return {
        "big_loser": max(0.0, (100.0 - conv) / 200.0),
        "big_winner": min(1.0, conv / 200.0),
        "stall": 0.25,
    }


def predict_gbm_probs(
    row: pd.Series | dict[str, Any],
    *,
    root: Path | None = None,
    conviction_fallback: float = 50.0,
) -> dict[str, float]:
    """Return class probabilities for one decision row."""
    root = root or project_root()
    if isinstance(row, dict):
        series = pd.Series(row)
    else:
        series = row

    run_id, feature_cols, classes = latest_gbm_artifact(root)
    if not run_id or not feature_cols:
        conv = float(series.get("conviction", conviction_fallback) or conviction_fallback)
        return heuristic_probs(conv)

    try:
        import lightgbm as lgb
    except ImportError:
        conv = float(series.get("conviction", conviction_fallback) or conviction_fallback)
        return heuristic_probs(conv)

    booster_dir = root / "data" / "learning" / "models" / run_id / "gbm"
    if not booster_dir.exists():
        conv = float(series.get("conviction", conviction_fallback) or conviction_fallback)
        return heuristic_probs(conv)

    boosters = sorted(booster_dir.glob("fold_*.txt"))
    if not boosters:
        boosters = sorted(booster_dir.glob("*.txt"))
    if not boosters:
        conv = float(series.get("conviction", conviction_fallback) or conviction_fallback)
        return heuristic_probs(conv)

    available = [c for c in feature_cols if c in series.index]
    if not available:
        conv = float(series.get("conviction", conviction_fallback) or conviction_fallback)
        return heuristic_probs(conv)

    X = pd.DataFrame([{c: float(pd.to_numeric(series.get(c), errors="coerce") or 0.0) for c in available}])
    prob_sum = None
    for path in boosters:
        model = lgb.Booster(model_file=str(path))
        raw = model.predict(X)
        arr = np.asarray(raw)
        if arr.ndim == 1:
            continue
        prob_sum = arr if prob_sum is None else prob_sum + arr
    if prob_sum is None:
        conv = float(series.get("conviction", conviction_fallback) or conviction_fallback)
        return heuristic_probs(conv)

    avg = prob_sum / len(boosters)
    if avg.ndim == 1:
        conv = float(series.get("conviction", conviction_fallback) or conviction_fallback)
        return heuristic_probs(conv)

    out: dict[str, float] = {}
    for idx, cls in enumerate(classes):
        if idx < avg.shape[1]:
            out[str(cls)] = float(avg[0, idx])
    return out or heuristic_probs(float(series.get("conviction", conviction_fallback) or conviction_fallback))
