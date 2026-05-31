"""Mature shadow scores with forward outcomes and labels."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_

from src.data.database import get_session
from src.data.models import DecisionShadowScore, TradeOutcome
from src.learning.evaluation.policies import BAD_LABELS
from src.utils.logger import get_logger

logger = get_logger("learning.evaluation.outcome_join")


def join_shadow_outcomes(*, lookback_days: int = 90) -> dict[str, Any]:
    """Attach matured outcome labels to shadow score rows."""
    session = get_session()
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    updated = 0
    matched = 0
    try:
        rows = (
            session.query(DecisionShadowScore)
            .filter(
                DecisionShadowScore.decision_ts >= cutoff,
                DecisionShadowScore.outcome_json.is_(None),
            )
            .all()
        )
        for row in rows:
            outcome = _match_outcome(session, row.ticker, row.decision_ts)
            if outcome is None:
                continue
            matched += 1
            label = _outcome_label(outcome)
            champion_bad = label in BAD_LABELS or label == "big_loser"
            challenger_would_skip = row.recommended_action == "skip"
            row.outcome_json = json.dumps(
                {
                    "trade_outcome_id": outcome.id,
                    "pnl_gbp": outcome.pnl_gbp,
                    "pnl_pct": outcome.pnl_pct,
                    "label_3class": label,
                    "champion_bad": champion_bad,
                    "challenger_would_skip": challenger_would_skip,
                    "counterfactual_correct": challenger_would_skip and champion_bad,
                    "counterfactual_missed_winner": challenger_would_skip and not champion_bad,
                },
                default=str,
            )
            row.matured_at = datetime.now(timezone.utc)
            updated += 1
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.exception("Shadow outcome join failed: %s", exc)
        return {"status": "failed", "error": str(exc)}
    finally:
        session.close()

    logger.info("Shadow outcome join: %s rows updated (%s matched)", updated, matched)
    return {"status": "completed", "updated": updated, "matched": matched}


def _match_outcome(session, ticker: str, decision_ts: datetime) -> TradeOutcome | None:
    window_end = decision_ts + timedelta(days=60)
    return (
        session.query(TradeOutcome)
        .filter(
            and_(
                TradeOutcome.ticker == ticker,
                TradeOutcome.buy_timestamp >= decision_ts - timedelta(hours=1),
                TradeOutcome.buy_timestamp <= window_end,
            )
        )
        .order_by(TradeOutcome.buy_timestamp.asc())
        .first()
    )


def _outcome_label(outcome: TradeOutcome) -> str:
    pnl_pct = float(outcome.pnl_pct or 0.0)
    if pnl_pct >= 10.0:
        return "big_winner"
    if pnl_pct <= -10.0:
        return "big_loser"
    holding = float(outcome.holding_days or 0.0)
    if abs(pnl_pct) <= 3.0 and holding >= 14.0:
        return "stall"
    return "neutral"


def shadow_summary(*, days: int = 30) -> dict[str, Any]:
    """Aggregate shadow scoring vs champion for dashboard."""
    session = get_session()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        rows = (
            session.query(DecisionShadowScore)
            .filter(DecisionShadowScore.decision_ts >= cutoff)
            .all()
        )
        if not rows:
            return {"days": days, "total_scores": 0, "by_policy": {}}

        by_policy: dict[str, dict[str, Any]] = {}
        for row in rows:
            bucket = by_policy.setdefault(
                row.policy_id,
                {
                    "policy_id": row.policy_id,
                    "n": 0,
                    "matured": 0,
                    "champion_bad": 0,
                    "veto_correct": 0,
                    "veto_missed_winner": 0,
                    "disagreements": 0,
                },
            )
            bucket["n"] += 1
            if row.recommended_action != row.champion_action:
                bucket["disagreements"] += 1
            if not row.outcome_json:
                continue
            bucket["matured"] += 1
            outcome = json.loads(row.outcome_json)
            if outcome.get("champion_bad"):
                bucket["champion_bad"] += 1
            if outcome.get("counterfactual_correct"):
                bucket["veto_correct"] += 1
            if outcome.get("counterfactual_missed_winner"):
                bucket["veto_missed_winner"] += 1

        span_days = days
        if rows:
            first = min(r.decision_ts for r in rows if r.decision_ts)
            span_days = max(1, (datetime.now(timezone.utc) - first).days)

        return {
            "days": days,
            "span_days": span_days,
            "total_scores": len(rows),
            "by_policy": by_policy,
        }
    finally:
        session.close()
