"""Offline counterfactual evaluation: champion vs challenger policies."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from src.data.database import get_session
from src.data.models import LearningRun
from src.learning.evaluation.policies import (
    BAD_LABELS,
    DEFAULT_EVAL_POLICIES,
    PolicyId,
    RecommendedAction,
)
from src.learning.spec import get_default_spec
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("learning.evaluation.counterfactual")


def _project_root() -> Path:
    override = os.environ.get("INVESTMENT_AGENT_LEARNING_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3]


def _is_bad_row(row: pd.Series) -> bool:
    label = str(row.get("label_3class") or "")
    if label in BAD_LABELS:
        return True
    ret30 = row.get("ret_30d")
    if ret30 is not None and not pd.isna(ret30) and float(ret30) <= -10.0:
        return True
    pnl = row.get("trade_pnl_gbp")
    if pnl is not None and not pd.isna(pnl) and float(pnl) < 0:
        realized_pct = row.get("realized_pnl_pct")
        if realized_pct is not None and not pd.isna(realized_pct) and float(realized_pct) <= -10.0:
            return True
    return label == "big_loser"


def _has_realized(row: pd.Series) -> bool:
    return bool(row.get("actually_traded")) or (
        row.get("trade_pnl_gbp") is not None and not pd.isna(row.get("trade_pnl_gbp"))
    )


def _recommend_champion(row: pd.Series) -> RecommendedAction:
    action = str(row.get("action") or "BUY").upper()
    if action == "QUEUED":
        return "queue"
    return "buy"


def _recommend_baseline_conviction(row: pd.Series) -> RecommendedAction:
    conv = float(row.get("conviction") or 50.0)
    if conv < 60:
        return "skip"
    if conv < 70:
        return "reduce_conviction"
    return "buy"


def _recommend_gbm(row: pd.Series, *, veto_threshold: float) -> RecommendedAction:
    p_bl = row.get("_p_big_loser")
    p_bw = row.get("_p_big_winner")
    if p_bl is not None and not pd.isna(p_bl) and float(p_bl) >= veto_threshold:
        return "skip"
    if p_bw is not None and not pd.isna(p_bw) and float(p_bw) >= 0.45:
        return "prioritize"
    return "buy"


def _recommend_calibrator(row: pd.Series) -> RecommendedAction:
    wr = row.get("_calibrated_win_rate")
    if wr is not None and not pd.isna(wr) and float(wr) < 0.25:
        return "skip"
    if wr is not None and not pd.isna(wr) and float(wr) >= 0.55:
        return "prioritize"
    return "buy"


def _recommend_memory(row: pd.Series, *, veto_threshold: float) -> RecommendedAction:
    frac_bad = row.get("_memory_bad_frac")
    if frac_bad is not None and not pd.isna(frac_bad) and float(frac_bad) >= veto_threshold:
        return "skip"
    return "buy"


def _recommend_combined(row: pd.Series, *, gbm_veto: float, mem_veto: float) -> RecommendedAction:
    if _recommend_gbm(row, veto_threshold=gbm_veto) == "skip":
        return "skip"
    if _recommend_memory(row, veto_threshold=mem_veto) == "skip":
        return "skip"
    if _recommend_gbm(row, veto_threshold=gbm_veto) == "prioritize":
        return "prioritize"
    return "buy"


def _attach_gbm_probs(df: pd.DataFrame, project_root: Path) -> pd.DataFrame:
    """Attach GBM probabilities via saved boosters or conviction heuristic."""
    out = df.copy()
    out["_p_big_loser"] = pd.NA
    out["_p_big_winner"] = pd.NA
    out["_p_stall"] = pd.NA

    run_id, feature_cols, classes = _latest_gbm_artifact(project_root)
    if run_id and feature_cols:
        try:
            preds = _predict_gbm(out, project_root, run_id, feature_cols, classes)
            if preds is not None:
                for col in preds.columns:
                    out[col] = preds[col].values
                return out
        except Exception as exc:
            logger.warning("GBM prediction failed, using heuristic: %s", exc)

    # Heuristic fallback: map conviction inversely to loser prob
    conv = out["conviction"].astype(float).fillna(50.0) if "conviction" in out.columns else 50.0
    out["_p_big_loser"] = (100.0 - conv) / 200.0
    out["_p_big_winner"] = conv / 200.0
    out["_p_stall"] = 0.25
    return out


def _latest_gbm_artifact(project_root: Path) -> tuple[str | None, list[str] | None, list[str]]:
    session = get_session()
    try:
        row = (
            session.query(LearningRun)
            .filter(LearningRun.status == "completed")
            .order_by(LearningRun.created_at.desc())
            .first()
        )
        if row is None:
            return None, None, ["big_loser", "stall", "big_winner"]
        metrics_path = project_root / "data" / "learning" / "reports" / row.run_id / "metrics.json"
        if not metrics_path.exists():
            return None, None, ["big_loser", "stall", "big_winner"]
        metrics = json.loads(metrics_path.read_text())
        gbm = metrics.get("gbm") or {}
        return row.run_id, gbm.get("feature_columns"), gbm.get("classes") or [
            "big_loser",
            "stall",
            "big_winner",
        ]
    finally:
        session.close()


def _predict_gbm(
    df: pd.DataFrame,
    project_root: Path,
    run_id: str,
    feature_cols: list[str],
    classes: list[str],
) -> pd.DataFrame | None:
    try:
        import lightgbm as lgb
    except ImportError:
        return None

    booster_dir = project_root / "data" / "learning" / "models" / run_id / "gbm"
    if not booster_dir.exists():
        return None
    boosters = sorted(booster_dir.glob("fold_*.txt"))
    if not boosters:
        boosters = sorted(booster_dir.glob("*.txt"))
    if not boosters:
        return None

    available = [c for c in feature_cols if c in df.columns]
    if not available:
        return None
    X = df[available].copy()
    for col in available:
        X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0.0)

    prob_sum = None
    for path in boosters:
        model = lgb.Booster(model_file=str(path))
        raw = model.predict(X)
        arr = np.asarray(raw)
        if arr.ndim == 1:
            continue
        prob_sum = arr if prob_sum is None else prob_sum + arr
    if prob_sum is None:
        return None
    prob_avg = prob_sum / len(boosters)
    result = pd.DataFrame(index=df.index)
    for idx, cls in enumerate(classes):
        if idx < prob_avg.shape[1]:
            result[f"_p_{cls}"] = prob_avg[:, idx]
    return result


def _attach_calibrator(df: pd.DataFrame, project_root: Path) -> pd.DataFrame:
    out = df.copy()
    out["_calibrated_win_rate"] = pd.NA
    run_id = _latest_train_run_id(project_root)
    if not run_id:
        return out
    cal_path = project_root / "data" / "learning" / "models" / run_id / "calibrator" / "calibrator.pkl"
    if not cal_path.exists():
        return out
    try:
        import pickle  # nosec B403

        with open(cal_path, "rb") as fh:
            calibrator = pickle.load(fh)  # nosec B301
        if "conviction" in out.columns:
            conv = out["conviction"].astype(float).fillna(50.0)
            out["_calibrated_win_rate"] = [calibrator.predict(c) for c in conv]
    except Exception as exc:
        logger.debug("Calibrator load failed: %s", exc)
    return out


def _latest_train_run_id(project_root: Path) -> str | None:
    session = get_session()
    try:
        row = (
            session.query(LearningRun)
            .filter(LearningRun.status == "completed")
            .order_by(LearningRun.created_at.desc())
            .first()
        )
        return row.run_id if row else None
    finally:
        session.close()


def _load_memory_index(project_root: Path) -> list[dict[str, Any]]:
    from src.learning.spec import get_text_corpus_spec

    path = project_root / get_text_corpus_spec().memory_bundle_path()
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _attach_memory_signals(df: pd.DataFrame, project_root: Path, k: int = 5) -> pd.DataFrame:
    out = df.copy()
    out["_memory_bad_frac"] = pd.NA
    out["_memory_retrieval_lift"] = pd.NA
    bundle = _load_memory_index(project_root)
    if not bundle:
        return out

    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for doc in bundle:
        ticker = str(doc.get("ticker") or "")
        by_ticker.setdefault(ticker, []).append(doc)

    bad_frac_list: list[float | None] = []
    for _, row in out.iterrows():
        ticker = str(row.get("ticker") or "")
        peers = by_ticker.get(ticker, [])
        if not peers:
            bad_frac_list.append(None)
            continue
        labels = [str(p.get("label_3class") or p.get("metadata", {}).get("label_3class") or "") for p in peers[:k]]
        if not labels:
            bad_frac_list.append(None)
            continue
        bad_count = sum(1 for lb in labels if lb in BAD_LABELS or lb == "big_loser")
        bad_frac_list.append(bad_count / len(labels))
    out["_memory_bad_frac"] = bad_frac_list
    return out


def _policy_metrics(
    df: pd.DataFrame,
    policy_id: PolicyId,
    recommendations: pd.Series,
) -> dict[str, Any]:
    n = len(df)
    bad_mask = df.apply(_is_bad_row, axis=1)
    realized_mask = df.apply(_has_realized, axis=1)
    realized_df = df.loc[realized_mask]
    realized_bad = bad_mask & realized_mask

    would_skip = recommendations.isin(["skip"])
    would_trade = ~would_skip

    saved = 0.0
    missed = 0.0
    if "trade_pnl_gbp" in df.columns and realized_mask.any():
        pnl = pd.to_numeric(df.loc[realized_mask, "trade_pnl_gbp"], errors="coerce").fillna(0.0)
        skip_realized = would_skip & realized_mask
        trade_realized = would_trade & realized_mask
        saved = float(-pnl[skip_realized & bad_mask.loc[realized_mask]].sum())
        missed = float(pnl[skip_realized & ~bad_mask.loc[realized_mask]].sum())

    vetoed = would_skip.sum()
    veto_hits = int((would_skip & bad_mask).sum())
    veto_total = int(would_skip.sum())
    losers = int(bad_mask.sum())
    loser_flagged = int((would_skip & bad_mask).sum())

    metrics: dict[str, Any] = {
        "policy_id": policy_id.value,
        "n_rows": n,
        "bad_decision_rate": float(bad_mask.mean()) if n else 0.0,
        "realized_n": int(realized_mask.sum()),
        "bad_decision_rate_realized": float(realized_bad.sum() / realized_mask.sum())
        if realized_mask.any()
        else None,
        "realized_pnl_gbp_sum": float(
            pd.to_numeric(df.loc[realized_mask, "trade_pnl_gbp"], errors="coerce").fillna(0.0).sum()
        )
        if realized_mask.any() and "trade_pnl_gbp" in df.columns
        else None,
        "counterfactual_pnl_gbp_saved": saved,
        "counterfactual_pnl_gbp_missed": missed,
        "net_counterfactual_gbp": saved - missed,
        "precision_at_veto": float(veto_hits / veto_total) if veto_total else None,
        "big_loser_recall": float(loser_flagged / losers) if losers else None,
        "veto_count": int(vetoed),
        "low_confidence": realized_mask.sum() < 200,
    }

    if policy_id == PolicyId.CHALLENGER_MEMORY and "_memory_bad_frac" in df.columns:
        valid = df["_memory_bad_frac"].dropna()
        if len(valid):
            metrics["memory_mean_bad_frac"] = float(valid.mean())

    return metrics


def _compute_rl_ope(project_root: Path) -> dict[str, Any]:
    spec = get_default_spec()
    merged_path = project_root / spec.output_dir / "parquet" / spec.version / "merged.parquet"
    if not merged_path.exists():
        return {}
    try:
        df = pd.read_parquet(merged_path)
        from src.learning.rl.evaluation import weighted_importance_sampling

        def champion_policy(row: pd.Series) -> Any:
            import numpy as np
            from src.learning.rl.env import ACTIONS, behaviour_action_from_row

            probs = np.zeros(len(ACTIONS), dtype=float)
            probs[behaviour_action_from_row(row)] = 1.0
            return probs

        wis = weighted_importance_sampling(df, champion_policy)
        return {"wis": wis.to_dict(), "champion_policy_value": wis.value_estimate}
    except Exception as exc:
        logger.debug("RL OPE skipped: %s", exc)
        return {}


def run_counterfactual_evaluation(
    *,
    project_root: str | Path | None = None,
    run_id: str | None = None,
    policies: Sequence[PolicyId] | None = None,
    write_report: bool = True,
) -> dict[str, Any]:
    """Run offline champion vs challenger counterfactual evaluation."""
    root = Path(project_root) if project_root else _project_root()
    settings = get_settings()
    spec = get_default_spec()
    run_id = run_id or datetime.now(timezone.utc).strftime("eval-%Y%m%dT%H%M%SZ")
    policy_list = list(policies or DEFAULT_EVAL_POLICIES)

    merged_path = root / spec.output_dir / "parquet" / spec.version / "merged.parquet"
    if not merged_path.exists():
        return {"run_id": run_id, "status": "failed", "error": f"merged parquet missing: {merged_path}"}

    df = pd.read_parquet(merged_path)
    if df.empty:
        return {"run_id": run_id, "status": "failed", "error": "merged dataset empty"}

    gbm_veto = float(getattr(settings, "learning_gbm_veto_threshold", 0.35))
    mem_veto = float(getattr(settings, "learning_memory_veto_threshold", 0.5))

    df = _attach_gbm_probs(df, root)
    df = _attach_calibrator(df, root)
    df = _attach_memory_signals(df, root)

    policy_metrics: dict[str, dict[str, Any]] = {}
    recommenders: dict[PolicyId, pd.Series] = {}

    for policy in policy_list:
        if policy == PolicyId.CHAMPION_AS_IS:
            recs = df.apply(_recommend_champion, axis=1)
        elif policy == PolicyId.BASELINE_CONVICTION:
            recs = df.apply(_recommend_baseline_conviction, axis=1)
        elif policy == PolicyId.CHALLENGER_GBM:
            recs = df.apply(lambda r: _recommend_gbm(r, veto_threshold=gbm_veto), axis=1)
        elif policy == PolicyId.CHALLENGER_CALIBRATOR:
            recs = df.apply(_recommend_calibrator, axis=1)
        elif policy == PolicyId.CHALLENGER_MEMORY:
            recs = df.apply(lambda r: _recommend_memory(r, veto_threshold=mem_veto), axis=1)
        elif policy == PolicyId.CHALLENGER_COMBINED:
            recs = df.apply(
                lambda r: _recommend_combined(r, gbm_veto=gbm_veto, mem_veto=mem_veto),
                axis=1,
            )
        elif policy == PolicyId.CHALLENGER_RL:
            recs = df.apply(_recommend_champion, axis=1)
        else:
            recs = df.apply(_recommend_champion, axis=1)
        recommenders[policy] = recs
        policy_metrics[policy.value] = _policy_metrics(df, policy, recs)

    rl_ope = {}
    if PolicyId.CHALLENGER_RL in policy_list or PolicyId.CHALLENGER_COMBINED in policy_list:
        rl_ope = _compute_rl_ope(root)

    train_metrics = _load_latest_train_metrics(root)
    closed_trades = int(policy_metrics.get(PolicyId.CHAMPION_AS_IS.value, {}).get("realized_n") or 0)

    from src.learning.evaluation.gates import check_promotion_gates

    eval_payload = {
        "run_id": run_id,
        "status": "completed",
        "dataset_version": spec.version,
        "merged_path": str(merged_path),
        "n_rows": len(df),
        "closed_trades": closed_trades,
        "policies": policy_metrics,
        "rl_ope": rl_ope,
        "artifact_run_id": _latest_train_run_id(root),
        "thresholds": {"gbm_veto": gbm_veto, "memory_veto": mem_veto},
    }
    gates = check_promotion_gates(
        evaluation_metrics=eval_payload,
        train_metrics=train_metrics,
        closed_trades=closed_trades,
    )
    eval_payload["gates"] = gates.to_dict()

    disagreements = _build_disagreements(df, recommenders, limit=100)
    eval_payload["disagreements"] = disagreements

    if write_report:
        from src.learning.evaluation.report import write_evaluation_report

        paths = write_evaluation_report(eval_payload, root=root)
        eval_payload["report_paths"] = paths
        _persist_evaluation_run(eval_payload, gates.to_dict())

    return eval_payload


def _load_latest_train_metrics(root: Path) -> dict[str, Any]:
    run_id = _latest_train_run_id(root)
    if not run_id:
        return {}
    path = root / "data" / "learning" / "reports" / run_id / "metrics.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _build_disagreements(
    df: pd.DataFrame,
    recommenders: dict[PolicyId, pd.Series],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    champion = recommenders.get(PolicyId.CHAMPION_AS_IS)
    combined = recommenders.get(PolicyId.CHALLENGER_COMBINED)
    if champion is None or combined is None:
        return []
    rows: list[dict[str, Any]] = []
    for idx in df.index:
        if champion.loc[idx] == combined.loc[idx]:
            continue
        row = df.loc[idx]
        rows.append(
            {
                "ticker": str(row.get("ticker") or ""),
                "cycle_id": str(row.get("cycle_id") or ""),
                "decision_ts": str(row.get("decision_ts") or ""),
                "label_3class": str(row.get("label_3class") or ""),
                "champion_action": champion.loc[idx],
                "combined_action": combined.loc[idx],
                "trade_pnl_gbp": row.get("trade_pnl_gbp"),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _persist_evaluation_run(payload: dict[str, Any], gates: dict[str, Any]) -> None:
    from src.data.models import LearningEvaluationRun

    session = get_session()
    try:
        existing = (
            session.query(LearningEvaluationRun)
            .filter(LearningEvaluationRun.run_id == payload["run_id"])
            .first()
        )
        row_data = {
            "dataset_version": payload.get("dataset_version", "v2"),
            "status": payload.get("status", "completed"),
            "n_rows": int(payload.get("n_rows") or 0),
            "closed_trades": int(payload.get("closed_trades") or 0),
            "metrics_json": json.dumps(payload, default=str),
            "gates_json": json.dumps(gates, default=str),
            "artifact_run_id": payload.get("artifact_run_id"),
            "error_message": payload.get("error"),
        }
        if existing:
            for k, v in row_data.items():
                setattr(existing, k, v)
        else:
            session.add(LearningEvaluationRun(run_id=payload["run_id"], **row_data))
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.warning("Failed to persist learning_evaluation_runs: %s", exc)
    finally:
        session.close()
