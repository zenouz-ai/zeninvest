"""Committee and context influence attribution helpers for offline evaluation."""

from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from src.data.models import OpportunityScoreSnapshot
from src.learning.evaluation.counterfactual import _is_bad_row
from src.learning.insights import (
    compute_guidance_sector_outcomes,
    compute_macro_regime_outcomes,
    compute_news_sentiment_outcomes,
    compute_screening_delta_outcomes,
)
from src.learning.spec import LabelConfig, get_default_spec


def _is_forward_winner(row: pd.Series, cfg: LabelConfig) -> bool:
    label = str(row.get("label_3class") or "")
    if label == "big_winner":
        return True
    ret30 = row.get("ret_30d")
    if ret30 is not None and not pd.isna(ret30):
        from src.agents.reporting.outcome_classification import is_big_winner

        return is_big_winner(float(ret30), 30.0, cfg)
    return False


def compute_committee_stratified(df: pd.DataFrame) -> dict[str, Any]:
    """Bad-rate breakdowns by moderation consensus, disagreement, and debate participation."""
    if df.empty:
        return {"by_consensus": [], "by_disagreement": [], "by_debate_change": [], "by_debate_rounds": []}

    work = df.copy()
    work["bad"] = work.apply(_is_bad_row, axis=1).astype(int)

    by_consensus: list[dict[str, Any]] = []
    if "moderation_consensus" in work.columns:
        for consensus, group in work.groupby(work["moderation_consensus"].fillna("UNKNOWN")):
            by_consensus.append(
                {
                    "moderation_consensus": str(consensus),
                    "n": int(len(group)),
                    "bad_rate": float(group["bad"].mean()),
                }
            )

    by_disagreement: list[dict[str, Any]] = []
    if "consensus_disagreement" in work.columns:
        for flag, group in work.groupby(work["consensus_disagreement"].fillna(-1)):
            by_disagreement.append(
                {
                    "consensus_disagreement": int(flag) if flag != -1 else None,
                    "n": int(len(group)),
                    "bad_rate": float(group["bad"].mean()),
                }
            )

    # Committee-debate slices (US-9.13). Guarded so pre-debate datasets don't break evaluate.
    by_debate_change: list[dict[str, Any]] = []
    if "verdict_changed_in_debate" in work.columns:
        debated = work[work["verdict_changed_in_debate"].notna()]
        for flag, group in debated.groupby(debated["verdict_changed_in_debate"].astype(int)):
            by_debate_change.append(
                {
                    "verdict_changed_in_debate": int(flag),
                    "n": int(len(group)),
                    "bad_rate": float(group["bad"].mean()),
                }
            )

    by_debate_rounds: list[dict[str, Any]] = []
    if "debate_rounds" in work.columns:
        rounds = work[work["debate_rounds"].notna()]
        for value, group in rounds.groupby(rounds["debate_rounds"].astype(int)):
            by_debate_rounds.append(
                {
                    "debate_rounds": int(value),
                    "n": int(len(group)),
                    "bad_rate": float(group["bad"].mean()),
                }
            )

    return {
        "by_consensus": by_consensus,
        "by_disagreement": by_disagreement,
        "by_debate_change": by_debate_change,
        "by_debate_rounds": by_debate_rounds,
    }


def compute_stage_funnel(df: pd.DataFrame, *, blocked_summary: dict[str, Any] | None = None) -> dict[str, int]:
    """Count proposals at each pipeline stage (observational)."""
    n_strategy = int(len(df))
    blocked = int((df.get("moderation_consensus", pd.Series(dtype=object)) == "BLOCKED").sum()) if not df.empty else 0
    risk_reject = int((df.get("risk_verdict", pd.Series(dtype=object)) == "REJECT").sum()) if not df.empty else 0
    traded = int(df.get("actually_traded", pd.Series(dtype=bool)).fillna(False).sum()) if not df.empty else 0
    realized = (
        int(df.get("trade_pnl_gbp", pd.Series(dtype=float)).notna().sum())
        if not df.empty and "trade_pnl_gbp" in df.columns
        else 0
    )

    funnel = {
        "strategy_buy_queued": n_strategy,
        "moderation_blocked": blocked,
        "risk_rejected": risk_reject,
        "executed": traded,
        "closed_realized": realized,
    }
    if blocked_summary:
        funnel["moderation_blocked_forward_labeled"] = int(blocked_summary.get("n_blocked", 0))
    return funnel


def summarize_blocked_trades(
    session: Session,
    merged_df: pd.DataFrame,
) -> dict[str, Any]:
    """Forward-label moderation-blocked rows from opportunity snapshots + merged parquet."""
    cfg = get_default_spec().labels
    blocked_rows = (
        session.query(OpportunityScoreSnapshot)
        .filter(OpportunityScoreSnapshot.stage == "moderation_blocked")
        .all()
    )
    if not blocked_rows:
        return {"n_blocked": 0, "good_block_rate": None, "missed_winner_rate": None, "samples": []}

    if merged_df.empty:
        return {"n_blocked": len(blocked_rows), "good_block_rate": None, "missed_winner_rate": None, "samples": []}

    merged = merged_df.copy()
    merged["_key"] = merged["cycle_id"].astype(str) + "|" + merged["ticker"].astype(str)

    good_blocks = 0
    missed_winners = 0
    matched = 0
    samples: list[dict[str, Any]] = []

    for row in blocked_rows:
        key = f"{row.cycle_id}|{row.ticker}"
        hit = merged[merged["_key"] == key]
        if hit.empty:
            continue
        m = hit.iloc[0]
        matched += 1
        is_bad = bool(_is_bad_row(m))
        is_winner = bool(_is_forward_winner(m, cfg))
        if is_bad:
            good_blocks += 1
        if is_winner:
            missed_winners += 1
        if len(samples) < 25:
            samples.append(
                {
                    "cycle_id": row.cycle_id,
                    "ticker": row.ticker,
                    "ret_30d": m.get("ret_30d"),
                    "label_3class": m.get("label_3class"),
                    "gpt_verdict": m.get("gpt_verdict"),
                    "gemini_verdict": m.get("gemini_verdict"),
                    "forward_bad": is_bad,
                    "forward_winner": is_winner,
                }
            )

    return {
        "n_blocked": len(blocked_rows),
        "n_matched_merged": matched,
        "good_block_rate": float(good_blocks / matched) if matched else None,
        "missed_winner_rate": float(missed_winners / matched) if matched else None,
        "samples": samples,
    }


def build_context_influence_report(df: pd.DataFrame) -> dict[str, Any]:
    """Stratified outcome tables for macro, guidance, news, and screening delta."""
    return {
        "macro_regime": compute_macro_regime_outcomes(df).to_dict(),
        "guidance_sector": compute_guidance_sector_outcomes(df).to_dict(),
        "news_sentiment": compute_news_sentiment_outcomes(df).to_dict(),
        "screening_delta": compute_screening_delta_outcomes(df).to_dict(),
    }


def extend_policy_forward_metrics(
    df: pd.DataFrame,
    recommendations: pd.Series,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    """Add forward-labeled veto precision and missed-winner rate to policy metrics."""
    cfg = get_default_spec().labels
    would_skip = recommendations.isin(["skip"])
    if not would_skip.any():
        metrics["missed_winner_rate"] = None
        metrics["forward_precision_at_veto"] = None
        metrics["net_counterfactual_forward_pct"] = None
        return metrics

    skip_df = df.loc[would_skip]
    bad_mask = skip_df.apply(_is_bad_row, axis=1)
    winner_mask = skip_df.apply(lambda r: _is_forward_winner(r, cfg), axis=1)
    veto_total = int(would_skip.sum())
    metrics["forward_precision_at_veto"] = float(bad_mask.sum() / veto_total) if veto_total else None
    metrics["missed_winner_rate"] = float(winner_mask.sum() / veto_total) if veto_total else None

    if "ret_30d" in df.columns:
        ret = pd.to_numeric(df.loc[would_skip, "ret_30d"], errors="coerce").fillna(0.0)
        saved = float(-ret[bad_mask].sum())
        missed = float(ret[winner_mask].sum())
        metrics["net_counterfactual_forward_pct"] = saved - missed
    else:
        metrics["net_counterfactual_forward_pct"] = None

    return metrics


def compute_debate_health(*, days: int = 30) -> dict[str, Any]:
    """Live committee-debate leading indicators from moderation_logs (no closed-trade gate).

    Mirrors ``shadow_summary``: opens its own session, queries a recent window, and returns a
    dict the dashboard can render immediately — without waiting for the weekly offline
    evaluation. Answers "is the debate doing anything, and at what cost?" before there are
    enough closed trades to judge forward outcomes.
    """
    from datetime import datetime, timedelta, timezone

    from src.data.database import get_session
    from src.data.models import CostLog, ModerationLog, ResearchLog

    session = get_session()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        mod_rows = session.query(ModerationLog).filter(ModerationLog.timestamp >= cutoff).all()

        decisions: dict[tuple[str, str], dict[str, Any]] = {}
        moderator_changes: list[int] = []
        per_moderator: dict[str, dict[str, int]] = {}
        for r in mod_rows:
            key = (r.cycle_id, r.ticker)
            d = decisions.setdefault(key, {"debate_rounds": None, "consensus": None})
            if r.debate_rounds is not None and d["debate_rounds"] is None:
                d["debate_rounds"] = r.debate_rounds
            if r.consensus and not d["consensus"]:
                d["consensus"] = r.consensus
            if r.verdict_changed_in_debate is not None:
                changed = 1 if r.verdict_changed_in_debate else 0
                moderator_changes.append(changed)
                pm = per_moderator.setdefault(r.moderator, {"n": 0, "changed": 0})
                pm["n"] += 1
                pm["changed"] += changed

        total_decisions = len(decisions)
        debated = sum(1 for d in decisions.values() if (d["debate_rounds"] or 1) >= 2)
        participation_rate = (debated / total_decisions) if total_decisions else 0.0
        churn_rate = (sum(moderator_changes) / len(moderator_changes)) if moderator_changes else 0.0

        rounds_distribution: dict[str, int] = {}
        consensus_mix: dict[str, int] = {}
        for d in decisions.values():
            rk = str(d["debate_rounds"] if d["debate_rounds"] is not None else 1)
            rounds_distribution[rk] = rounds_distribution.get(rk, 0) + 1
            ck = d["consensus"] or "UNKNOWN"
            consensus_mix[ck] = consensus_mix.get(ck, 0) + 1

        per_moderator_churn = {
            mod: {"n": v["n"], "churn_rate": round(v["changed"] / v["n"], 4) if v["n"] else 0.0}
            for mod, v in per_moderator.items()
        }

        skeptic_tool_calls = (
            session.query(ResearchLog)
            .filter(ResearchLog.created_at >= cutoff, ResearchLog.member == "skeptic")
            .count()
        )

        moderation_cost_gbp = float(
            sum(
                (row.cost_gbp or 0.0)
                for row in session.query(CostLog)
                .filter(
                    CostLog.timestamp >= cutoff,
                    CostLog.purpose.in_(["moderation_gpt4o", "moderation_gemini"]),
                )
                .all()
            )
        )

        return {
            "days": days,
            "total_decisions": total_decisions,
            "debate_participation_rate": round(participation_rate, 4),
            "debate_churn_rate": round(churn_rate, 4),
            "per_moderator_churn": per_moderator_churn,
            "rounds_distribution": rounds_distribution,
            "consensus_mix": consensus_mix,
            "skeptic_tool_calls": int(skeptic_tool_calls),
            "moderation_cost_gbp": round(moderation_cost_gbp, 4),
        }
    finally:
        session.close()
