#!/usr/bin/env python3
"""Read-only proof-of-value analysis of rejected-ticker decisions (US-6.7 spike).

Question this answers
---------------------
The learning/eval stack only ever sees tickers we *bought* (``StrategyDecision.action
IN ("BUY","QUEUED")``). This spike looks at the other side of the funnel: the names
the pipeline *considered but declined*. It measures whether those rejected tickers
went on to underperform ("good misses" that validate the gate) and what our
"false rejects" -- declined names that became winners -- would have cost us.

How it works
------------
* Rejected population is reconstructed from ``OpportunityScoreSnapshot`` -- the
  per-ticker, per-cycle decision journal that already stores ``is_tradable``,
  ``stage`` (strategy_hold / moderation_blocked / risk_reject / opportunity_filtered),
  and the frozen decision-time sub-scores for **every** evaluated name.
* Forward outcomes are computed with the SAME machinery the learning labels use
  (:class:`src.learning.dataset.labels.LabelComputer`) so the bands line up with the
  v6 north-star definition. We derive a pure forward (mark-to-market) counterfactual
  label from the forward return + drawdown so a rejected name that we happened to buy
  in a later cycle is not conflated with its real trade.

Guarantees
----------
* **Read-only.** Never writes to any database; never influences live trading.
* Honours ``INVESTMENT_AGENT_DB_PATH`` and ``--db-path`` so it can run against the
  committed dev fixture (``fixtures/dev/investment_agent.db``) or a live DB.

Usage
-----
    poetry run python scripts/analyze_rejected_tickers.py
    poetry run python scripts/analyze_rejected_tickers.py --db-path fixtures/dev/investment_agent.db
    INVESTMENT_AGENT_DB_PATH=fixtures/dev/investment_agent.db \
        poetry run python scripts/analyze_rejected_tickers.py
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session, sessionmaker

from src.agents.reporting.outcome_classification import label_from_gain_per_day
from src.data.models import OpportunityScoreSnapshot
from src.learning.dataset.labels import LabelComputer
from src.learning.spec import DatasetSpec, get_default_spec
from src.utils.ticker_utils import t212_to_yf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "learning" / "reports"

WINNER = "big_winner"
STALL = "stall"
LOSER = "big_loser"


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class StageStats:
    """Per-rejection-stage diagnostics."""

    stage: str
    n: int
    n_resolved: int
    good_miss_rate: float | None  # resolved rejects that became big_loser (justified veto)
    false_reject_rate: float | None  # resolved rejects that became big_winner (missed winner)
    stall_rate: float | None
    mean_forward_ret_pct: float | None


@dataclass
class RejectionAnalysis:
    """Top-level proof-of-value summary."""

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
    selection_gap_pct: float | None  # accepted minus rejected mean forward return
    rejected_label_counts: dict[str, int] = field(default_factory=dict)
    accepted_label_counts: dict[str, int] = field(default_factory=dict)
    by_stage: list[StageStats] = field(default_factory=list)

    def to_json(self) -> dict:
        d = asdict(self)
        d["by_stage"] = [asdict(s) for s in self.by_stage]
        return d


# ---------------------------------------------------------------------------
# Data loading + label computation
# ---------------------------------------------------------------------------


def _market_cache_available(session: Session) -> bool:
    """True if the ``market_data_cache`` fallback table exists (absent in the dev fixture)."""

    try:
        return "market_data_cache" in sa_inspect(session.get_bind()).get_table_names()
    except Exception:
        return False


_EMPTY_PRICES = pd.DataFrame(columns=["date", "close", "high", "low"])


def make_yfinance_only_fetcher() -> Callable[[str, datetime, int], pd.DataFrame]:
    """A forward-price fetcher that uses yfinance only and never touches the DB.

    Returns an **empty** DataFrame on any miss so LabelComputer does not fall through
    to its ``market_data_cache`` query (which is stripped from the sanitized fixture).
    Used when the cache table is unavailable; on the VPS the default cascade is preferred.
    """

    cache: dict[str, pd.DataFrame | None] = {}

    def fetch(ticker: str, decision_ts: datetime, max_days: int) -> pd.DataFrame:
        try:
            symbol = t212_to_yf(ticker)
        except Exception:
            return _EMPTY_PRICES
        if symbol not in cache:
            try:  # pragma: no cover - network optional
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
    """Decision-time rows for accepted (``is_tradable=True``) or rejected names."""

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
    """Pure forward (MTM) v6 label, mirroring the Phase-A fallback in LabelComputer.

    Returns ``None`` when there is not enough forward price data to resolve.
    """

    if ret is None or (isinstance(ret, float) and pd.isna(ret)):
        return None
    cfg = spec.labels
    label = label_from_gain_per_day(float(ret), float(horizon_days), cfg)
    # Drawdown veto: a name that bled through the big_winner drawdown floor cannot
    # be counted as a clean winner (matches labels.py big_winner_max_drawdown_pct).
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
    """Attach forward returns + a forward counterfactual label to each row."""

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


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _mean(series: pd.Series) -> float | None:
    clean = series.dropna()
    return round(float(clean.mean()), 4) if not clean.empty else None


def _label_counts(df: pd.DataFrame) -> dict[str, int]:
    counts = df["cf_label"].value_counts(dropna=True).to_dict()
    return {k: int(v) for k, v in counts.items()}


def analyze_rejections(
    session: Session,
    *,
    spec: DatasetSpec | None = None,
    label_computer: LabelComputer | None = None,
) -> RejectionAnalysis:
    """Compute the rejected-vs-accepted proof-of-value summary."""

    spec = spec or get_default_spec()
    horizon = max(spec.labels.horizons_days)

    if label_computer is None:
        # On the VPS the default yfinance -> market_data_cache cascade is best; when the
        # cache table is absent (sanitized fixture) avoid it so we don't crash.
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
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "n/a"


def _num(value: float | None) -> str:
    return f"{value:+.2f}%" if value is not None else "n/a"


def render_markdown(a: RejectionAnalysis) -> str:
    lines = [
        "# Rejected-Ticker Decision Analysis — Proof of Value",
        "",
        f"_Generated {a.generated_at} · forward horizon {a.horizon_days}d · "
        "mark-to-market counterfactual using v6 gain/day bands._",
        "",
        "## Headline",
        "",
        f"- Rejected decisions analysed: **{a.rejected_total}** "
        f"(forward-resolvable: {a.rejected_resolved}, coverage {_pct(a.coverage_pct)})",
        f"- **Good-miss rate** (rejected → big_loser, veto justified): **{_pct(a.good_miss_rate)}**",
        f"- **False-reject rate** (rejected → big_winner, missed winner): **{_pct(a.false_reject_rate)}**",
        f"- Stall rate (rejected → stall): {_pct(a.stall_rate)}",
        "",
        "## Selection signal (accepted vs rejected)",
        "",
        f"- Mean forward return of **accepted** names: {_num(a.accepted_mean_forward_ret_pct)} "
        f"(n={a.accepted_resolved})",
        f"- Mean forward return of **rejected** names: {_num(a.rejected_mean_forward_ret_pct)} "
        f"(n={a.rejected_resolved})",
        f"- **Selection gap** (accepted − rejected): {_num(a.selection_gap_pct)}  "
        "_(positive ⇒ the funnel pushed lower-return names out; this gap is also the "
        "magnitude of the selection bias baked into the traded-only learning set)_",
        "",
        "## Per-stage veto quality",
        "",
        "| Stage | n | resolved | good-miss | false-reject | stall | mean fwd ret |",
        "|-------|---|----------|-----------|--------------|-------|--------------|",
    ]
    for s in a.by_stage:
        lines.append(
            f"| {s.stage} | {s.n} | {s.n_resolved} | {_pct(s.good_miss_rate)} | "
            f"{_pct(s.false_reject_rate)} | {_pct(s.stall_rate)} | {_num(s.mean_forward_ret_pct)} |"
        )
    lines += [
        "",
        "## Reading this",
        "",
        "- A **high good-miss rate** with a **low false-reject rate** validates that the gate "
        "rejects bad investments.",
        "- A stage with a **high false-reject rate** is destroying value — it is vetoing names "
        "that would have been winners and is the first candidate for threshold re-tuning.",
        "- A **positive selection gap** confirms the learning dataset is censored (the names we "
        "train on are not a random sample), motivating the reject-inference work in US-6.7.",
        "",
        "_Caveats: mark-to-market forward returns ignore execution/slippage and position sizing; "
        "coverage < 100% reflects delisted or thinly-cached tickers; small per-stage samples are "
        "noisy. This is a directional proof of value, not a P&L claim._",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Session + CLI
# ---------------------------------------------------------------------------


def build_readonly_session(db_path: str | None) -> Session:
    """Build a standalone session over an explicit SQLite file (read-only intent)."""

    resolved = db_path or os.environ.get("INVESTMENT_AGENT_DB_PATH") or str(
        PROJECT_ROOT / "data" / "investment_agent.db"
    )
    engine = create_engine(f"sqlite:///{resolved}")
    return sessionmaker(bind=engine)()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", default=None, help="SQLite DB path (else INVESTMENT_AGENT_DB_PATH / live DB)")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Where to write the json/markdown summary")
    parser.add_argument("--no-write", action="store_true", help="Print only; do not write summary files")
    args = parser.parse_args()

    session = build_readonly_session(args.db_path)
    try:
        analysis = analyze_rejections(session)
    finally:
        session.close()

    markdown = render_markdown(analysis)
    print(markdown)

    if not args.no_write:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        (out_dir / f"rejected_analysis_{stamp}.json").write_text(json.dumps(analysis.to_json(), indent=2))
        (out_dir / f"rejected_analysis_{stamp}.md").write_text(markdown)
        print(f"Wrote summary to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
