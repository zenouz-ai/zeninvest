"""Rejected-decision counterfactual analysis (US-6.7)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from src.agents.reporting.outcome_classification import label_from_gain_per_day
from src.data.models import OpportunityScoreSnapshot
from src.learning.dataset.labels import LabelComputer
from src.learning.spec import DatasetSpec, get_default_spec
from src.utils.ticker_utils import t212_to_yf

WINNER = "big_winner"
STALL = "stall"
LOSER = "big_loser"

DEFAULT_REPORTS_DIR = Path("data/learning/reports")


@dataclass
class StageStats:
    stage: str
    n: int
    n_resolved: int
    good_miss_rate: float | None
    false_reject_rate: float | None
    stall_rate: float | None
    mean_forward_ret_pct: float | None


@dataclass
class RejectionAnalysis:
    generated_at: str
    horizon_days: int
    rejected_total: int
    rejected_resolved: int
    accepted_total: int
    accepted_resolved: int
    coverage_pct: float | None
    good_miss_rate: float | None
    false_reject_rate: float | None
    stall_rate: float | None
    rejected_mean_forward_ret_pct: float | None
    accepted_mean_forward_ret_pct: float | None
    selection_gap_pct: float | None
    rejected_label_counts: dict[str, int] = field(default_factory=dict)
    accepted_label_counts: dict[str, int] = field(default_factory=dict)
    by_stage: list[StageStats] = field(default_factory=list)
    funnel_metrics: dict[str, float | int | None] | None = None

    def to_json(self) -> dict:
        d = asdict(self)
        d["by_stage"] = [asdict(s) for s in self.by_stage]
        return d


def _market_cache_available(session: Session) -> bool:
    try:
        return "market_data_cache" in sa_inspect(session.get_bind()).get_table_names()
    except Exception:
        return False


_EMPTY_PRICES = pd.DataFrame(columns=["date", "close", "high", "low"])


def make_yfinance_only_fetcher() -> Callable[[str, datetime, int], pd.DataFrame]:
    cache: dict[str, pd.DataFrame | None] = {}

    def fetch(ticker: str, decision_ts: datetime, max_days: int) -> pd.DataFrame:
        try:
            symbol = t212_to_yf(ticker)
        except Exception:
            return _EMPTY_PRICES
        if symbol not in cache:
            try:  # pragma: no cover
                import yfinance as yf  # type: ignore

                hist = yf.Ticker(symbol).history(period="2y", auto_adjust=False)
                if hist is None or hist.empty:
                    cache[symbol] = None
                else:
                    df = hist.reset_index()[["Date", "Close", "High", "Low"]].copy()
                    df.columns = ["date", "close", "high", "low"]
                    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
                    cache[symbol] = df
            except Exception:  # pragma: no cover
                cache[symbol] = None
        df = cache[symbol]
        if df is None or df.empty:
            return _EMPTY_PRICES
        lower = decision_ts - timedelta(days=2)
        upper = decision_ts + timedelta(days=max_days + 5)
        window = df[(df["date"] >= lower) & (df["date"] <= upper)].copy()
        return window if not window.empty else _EMPTY_PRICES

    return fetch


def load_snapshot_rows(session: Session, *, is_tradable: bool) -> list[dict]:
    rows = (
        session.query(OpportunityScoreSnapshot)
        .filter(OpportunityScoreSnapshot.is_tradable.is_(is_tradable))
        .order_by(OpportunityScoreSnapshot.timestamp.asc())
        .all()
    )
    out: list[dict] = []
    for r in rows:
        if not r.cycle_id or not r.ticker or not isinstance(r.timestamp, datetime):
            continue
        out.append(
            {
                "cycle_id": r.cycle_id,
                "ticker": r.ticker,
                "timestamp": r.timestamp,
                "stage": r.stage or "unknown",
            }
        )
    return out


def _counterfactual_label(
    ret: float | None,
    drawdown: float | None,
    horizon_days: int,
    spec: DatasetSpec,
) -> str | None:
    if ret is None or pd.isna(ret):
        return None
    cfg = spec.labels
    label = label_from_gain_per_day(float(ret), float(horizon_days), cfg)
    if (
        label == WINNER
        and drawdown is not None
        and not pd.isna(drawdown)
        and float(drawdown) <= cfg.big_winner_max_drawdown_pct
    ):
        return STALL
    return label


def label_rows(
    session: Session,
    rows: list[dict],
    *,
    spec: DatasetSpec,
    label_computer: LabelComputer | None = None,
) -> pd.DataFrame:
    horizon = max(spec.labels.horizons_days)
    base = pd.DataFrame(rows, columns=["cycle_id", "ticker", "timestamp", "stage"])
    if base.empty:
        base["forward_ret_pct"] = []
        base["cf_label"] = []
        return base

    computer = label_computer or LabelComputer(session, spec=spec)
    labels = computer.compute(rows)
    ret_col = f"ret_{horizon}d"
    dd_col = f"mtm_max_drawdown_{horizon}d"
    keep = labels[["cycle_id", "ticker"]].copy()
    keep["forward_ret_pct"] = labels.get(ret_col)
    drawdowns = labels.get(dd_col)
    keep["forward_drawdown_pct"] = drawdowns if drawdowns is not None else None
    merged = base.merge(keep, on=["cycle_id", "ticker"], how="left")
    merged["cf_label"] = [
        _counterfactual_label(ret, dd, horizon, spec)
        for ret, dd in zip(merged["forward_ret_pct"], merged.get("forward_drawdown_pct"))
    ]
    return merged


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _mean(series: pd.Series) -> float | None:
    clean = series.dropna()
    return round(float(clean.mean()), 4) if not clean.empty else None


def _label_counts(df: pd.DataFrame) -> dict[str, int]:
    counts = df["cf_label"].value_counts(dropna=True).to_dict()
    return {k: int(v) for k, v in counts.items()}


def compute_funnel_metrics(rejected: pd.DataFrame, accepted: pd.DataFrame) -> dict[str, float | int | None]:
    """Full-funnel veto quality across rejected + accepted populations."""
    rej_resolved = rejected[rejected["cf_label"].notna()]
    acc_resolved = accepted[accepted["cf_label"].notna()]
    total_evaluated = len(rejected) + len(accepted)
    veto_total = len(rej_resolved)
    good_misses = int((rej_resolved["cf_label"] == LOSER).sum())
    false_rejects = int((rej_resolved["cf_label"] == WINNER).sum())
    return {
        "total_evaluated": total_evaluated,
        "rejected_count": len(rejected),
        "accepted_count": len(accepted),
        "forward_precision_at_veto": _rate(good_misses, veto_total),
        "missed_winner_rate": _rate(false_rejects, veto_total),
        "accepted_winner_rate": _rate(int((acc_resolved["cf_label"] == WINNER).sum()), len(acc_resolved)),
        "selection_gap_pct": (
            round(_mean(acc_resolved["forward_ret_pct"]) - _mean(rej_resolved["forward_ret_pct"]), 4)  # type: ignore[operator]
            if _mean(acc_resolved["forward_ret_pct"]) is not None and _mean(rej_resolved["forward_ret_pct"]) is not None
            else None
        ),
    }


def analyze_rejections(
    session: Session,
    *,
    spec: DatasetSpec | None = None,
    label_computer: LabelComputer | None = None,
) -> RejectionAnalysis:
    spec = spec or get_default_spec()
    horizon = max(spec.labels.horizons_days)

    if label_computer is None:
        fetcher = None if _market_cache_available(session) else make_yfinance_only_fetcher()
        label_computer = LabelComputer(session, spec=spec, price_fetcher=fetcher)

    rejected = label_rows(
        session, load_snapshot_rows(session, is_tradable=False), spec=spec, label_computer=label_computer
    )
    accepted = label_rows(
        session, load_snapshot_rows(session, is_tradable=True), spec=spec, label_computer=label_computer
    )

    rej_resolved = rejected[rejected["cf_label"].notna()]
    acc_resolved = accepted[accepted["cf_label"].notna()]
    n_rej_res = len(rej_resolved)

    by_stage: list[StageStats] = []
    for stage, group in rejected.groupby("stage"):
        resolved = group[group["cf_label"].notna()]
        n_res = len(resolved)
        by_stage.append(
            StageStats(
                stage=str(stage),
                n=len(group),
                n_resolved=n_res,
                good_miss_rate=_rate(int((resolved["cf_label"] == LOSER).sum()), n_res),
                false_reject_rate=_rate(int((resolved["cf_label"] == WINNER).sum()), n_res),
                stall_rate=_rate(int((resolved["cf_label"] == STALL).sum()), n_res),
                mean_forward_ret_pct=_mean(resolved["forward_ret_pct"]),
            )
        )
    by_stage.sort(key=lambda s: s.n, reverse=True)

    rej_mean = _mean(rej_resolved["forward_ret_pct"])
    acc_mean = _mean(acc_resolved["forward_ret_pct"])
    gap = round(acc_mean - rej_mean, 4) if acc_mean is not None and rej_mean is not None else None

    funnel = compute_funnel_metrics(rejected, accepted)

    return RejectionAnalysis(
        generated_at=datetime.now(timezone.utc).isoformat(),
        horizon_days=horizon,
        rejected_total=len(rejected),
        rejected_resolved=n_rej_res,
        accepted_total=len(accepted),
        accepted_resolved=len(acc_resolved),
        coverage_pct=_rate(n_rej_res, len(rejected)),
        good_miss_rate=_rate(int((rej_resolved["cf_label"] == LOSER).sum()), n_rej_res),
        false_reject_rate=_rate(int((rej_resolved["cf_label"] == WINNER).sum()), n_rej_res),
        stall_rate=_rate(int((rej_resolved["cf_label"] == STALL).sum()), n_rej_res),
        rejected_mean_forward_ret_pct=rej_mean,
        accepted_mean_forward_ret_pct=acc_mean,
        selection_gap_pct=gap,
        rejected_label_counts=_label_counts(rej_resolved),
        accepted_label_counts=_label_counts(acc_resolved),
        by_stage=by_stage,
        funnel_metrics=funnel,
    )


def _learning_root() -> Path:
    override = os.environ.get("INVESTMENT_AGENT_LEARNING_ROOT")
    if override:
        return Path(override)
    return Path("data/learning")


def reports_dir() -> Path:
    return _learning_root() / "reports"


def _pct(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "n/a"


def _num(value: float | None) -> str:
    return f"{value:+.2f}%" if value is not None else "n/a"


def render_markdown(a: RejectionAnalysis) -> str:
    lines = [
        "# Rejected-Ticker Decision Analysis — Proof of Value",
        "",
        f"_Generated {a.generated_at} · forward horizon {a.horizon_days}d_",
        "",
        f"- Good-miss rate: **{_pct(a.good_miss_rate)}**",
        f"- False-reject rate: **{_pct(a.false_reject_rate)}**",
        f"- Selection gap: {_num(a.selection_gap_pct)}",
        "",
        "| Stage | n | good-miss | false-reject |",
        "|-------|---|-----------|--------------|",
    ]
    for s in a.by_stage:
        lines.append(
            f"| {s.stage} | {s.n} | {_pct(s.good_miss_rate)} | {_pct(s.false_reject_rate)} |"
        )
    return "\n".join(lines) + "\n"


def write_analysis_artifacts(analysis: RejectionAnalysis, output_dir: Path | None = None) -> dict[str, str]:
    out_dir = output_dir or reports_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    json_path = out_dir / f"rejected_analysis_{stamp}.json"
    json_path.write_text(json.dumps(analysis.to_json(), indent=2))
    return {"json": str(json_path), "stamp": stamp}


def load_latest_rejection_analysis() -> dict[str, Any] | None:
    """Load the most recent precomputed rejected_analysis_*.json artifact."""
    candidates = sorted(reports_dir().glob("rejected_analysis_*.json")) if reports_dir().exists() else []
    if not candidates:
        return None
    try:
        return json.loads(candidates[-1].read_text())
    except (json.JSONDecodeError, OSError):
        return None


def rejection_analysis_freshness() -> dict[str, Any]:
    """Headline freshness for dashboard bootstrap (mtime + key counts)."""
    candidates = sorted(reports_dir().glob("rejected_analysis_*.json")) if reports_dir().exists() else []
    if not candidates:
        return {"available": False}
    path = candidates[-1]
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"available": False, "artifact_name": path.name}
    stat = path.stat()
    return {
        "available": True,
        "artifact_name": path.name,
        "generated_at": payload.get("generated_at"),
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "rejected_total": payload.get("rejected_total"),
        "coverage_pct": payload.get("coverage_pct"),
        "false_reject_rate": payload.get("false_reject_rate"),
        "good_miss_rate": payload.get("good_miss_rate"),
        "selection_gap_pct": payload.get("selection_gap_pct"),
        "history_count": len(candidates),
    }


def load_rejection_history(limit: int = 12) -> list[dict]:
    """Load headline metrics from historical rejected_analysis_*.json artifacts."""
    candidates = sorted(reports_dir().glob("rejected_analysis_*.json")) if reports_dir().exists() else []
    history: list[dict] = []
    for path in candidates[-limit:]:
        try:
            payload = json.loads(path.read_text())
            history.append(
                {
                    "artifact_name": path.name,
                    "generated_at": payload.get("generated_at"),
                    "good_miss_rate": payload.get("good_miss_rate"),
                    "false_reject_rate": payload.get("false_reject_rate"),
                    "selection_gap_pct": payload.get("selection_gap_pct"),
                    "coverage_pct": payload.get("coverage_pct"),
                    "rejected_total": payload.get("rejected_total"),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    return history
