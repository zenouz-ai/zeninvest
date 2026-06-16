"""Automated promotion gate checker for shadow learning policies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.learning.evaluation.policies import PolicyId

# Canonical thresholds (single source of truth — docs reference these tiers).
GATE_MIN_CLOSED_TRADES_SHADOW_LIVE = 50
GATE_MIN_CLOSED_TRADES_INFLUENCE_REVIEW = 200
GATE_MIN_CLOSED_TRADES_LIVE_INFLUENCE = 500
GATE_MIN_SHADOW_CALENDAR_DAYS = 30
GATE_MIN_WALK_FORWARD_FOLDS = 2
GATE_MIN_TOP_DECILE_LIFT_PCT = 3.0
GATE_MIN_WIS_ESS = 200
GATE_MIN_MEMORY_VETO_PRECISION = 0.40
GATE_MIN_STALL_AUC = 0.52
GATE_MIN_GBM_BIG_WINNER_RECALL = 0.35


@dataclass
class GateTier:
    tier_id: str
    label: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
    requirements: dict[str, Any] = field(default_factory=dict)


@dataclass
class GateReport:
    tiers: list[GateTier]
    stop_the_line: list[str] = field(default_factory=list)
    promotion_ready: bool = False
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tiers": [
                {
                    "tier_id": t.tier_id,
                    "label": t.label,
                    "passed": t.passed,
                    "reasons": t.reasons,
                    "requirements": t.requirements,
                }
                for t in self.tiers
            ],
            "stop_the_line": self.stop_the_line,
            "promotion_ready": self.promotion_ready,
            "summary": self.summary,
        }


def check_promotion_gates(
    *,
    evaluation_metrics: dict[str, Any],
    train_metrics: dict[str, Any] | None = None,
    closed_trades: int = 0,
    shadow_days: int = 0,
    shadow_rows: int = 0,
) -> GateReport:
    """Evaluate gate tiers from counterfactual + optional train metrics."""
    train_metrics = train_metrics or {}
    gbm = train_metrics.get("gbm") or {}
    agg = gbm.get("aggregate_metrics") or {}
    baselines = train_metrics.get("baselines") or {}
    stall = train_metrics.get("stall") or {}
    stop: list[str] = []

    per_class_recall = agg.get("per_class_recall") or {}
    gbm_bl_recall = float(per_class_recall.get("big_loser") or 0.0)
    gbm_bw_recall = float(per_class_recall.get("big_winner") or 0.0)
    baseline_bl = _baseline_big_loser_recall(baselines)
    if gbm and baseline_bl is not None and gbm_bl_recall < baseline_bl:
        stop.append(
            f"GBM big_loser recall ({gbm_bl_recall:.1%}) regressed vs conviction baseline ({baseline_bl:.1%})"
        )
    if gbm and gbm_bw_recall < GATE_MIN_GBM_BIG_WINNER_RECALL:
        stop.append(
            f"GBM big_winner recall ({gbm_bw_recall:.1%}) below floor {GATE_MIN_GBM_BIG_WINNER_RECALL:.0%}"
        )

    stall_auc = float((stall.get("aggregate_metrics") or {}).get("auc") or 0.0)
    if stall and stall_auc < GATE_MIN_STALL_AUC:
        stop.append(f"Stall AUC ({stall_auc:.3f}) below floor {GATE_MIN_STALL_AUC}")

    challenger_gbm = evaluation_metrics.get("policies", {}).get(PolicyId.CHALLENGER_GBM, {})
    memory_precision = challenger_gbm.get("precision_at_veto")
    mem_policy = evaluation_metrics.get("policies", {}).get(PolicyId.CHALLENGER_MEMORY, {})
    mem_precision = mem_policy.get("precision_at_veto")
    if mem_precision is not None and mem_precision < GATE_MIN_MEMORY_VETO_PRECISION:
        stop.append(
            f"Memory veto precision ({mem_precision:.1%}) below {GATE_MIN_MEMORY_VETO_PRECISION:.0%}"
        )

    champion = evaluation_metrics.get("policies", {}).get(PolicyId.CHAMPION_AS_IS, {})
    combined = evaluation_metrics.get("policies", {}).get(PolicyId.CHALLENGER_COMBINED, {})
    net_cf = combined.get("net_counterfactual_gbp")
    realized_n = int(champion.get("realized_n") or closed_trades or 0)

    tiers: list[GateTier] = []

    # Tier 1: Shadow OK (offline counterfactual completes)
    tier1_ok = bool(evaluation_metrics.get("run_id")) and not evaluation_metrics.get("error")
    tiers.append(
        GateTier(
            tier_id="shadow_ok",
            label="Shadow OK (offline counterfactual)",
            passed=tier1_ok and not stop,
            reasons=[] if tier1_ok else ["Counterfactual evaluation did not complete"],
            requirements={"min_closed_trades": 0},
        )
    )

    # Tier 2: Shadow live scoring
    tier2_ok = shadow_rows > 0 and shadow_days >= GATE_MIN_SHADOW_CALENDAR_DAYS
    tier2_reasons: list[str] = []
    if shadow_rows == 0:
        tier2_reasons.append("No shadow score rows logged yet")
    if shadow_days < GATE_MIN_SHADOW_CALENDAR_DAYS:
        tier2_reasons.append(
            f"Shadow logging span {shadow_days}d < {GATE_MIN_SHADOW_CALENDAR_DAYS}d required"
        )
    tiers.append(
        GateTier(
            tier_id="shadow_live",
            label="Shadow live scoring",
            passed=tier2_ok and realized_n >= GATE_MIN_CLOSED_TRADES_SHADOW_LIVE,
            reasons=tier2_reasons
            + (
                []
                if realized_n >= GATE_MIN_CLOSED_TRADES_SHADOW_LIVE
                else [f"Closed trades {realized_n} < {GATE_MIN_CLOSED_TRADES_SHADOW_LIVE}"]
            ),
            requirements={
                "min_closed_trades": GATE_MIN_CLOSED_TRADES_SHADOW_LIVE,
                "min_shadow_days": GATE_MIN_SHADOW_CALENDAR_DAYS,
            },
        )
    )

    # Tier 3: Influence review
    decile_lift = _top_decile_lift(gbm)
    n_folds = int(agg.get("n_folds") or 0)
    rl_ope = evaluation_metrics.get("rl_ope") or {}
    wis_ess = float((rl_ope.get("wis") or {}).get("diagnostic", {}).get("effective_sample_size") or 0)
    tier3_ok = (
        realized_n >= GATE_MIN_CLOSED_TRADES_INFLUENCE_REVIEW
        and net_cf is not None
        and float(net_cf) > 0
        and decile_lift is not None
        and decile_lift >= GATE_MIN_TOP_DECILE_LIFT_PCT
        and n_folds >= GATE_MIN_WALK_FORWARD_FOLDS
    )
    tier3_reasons: list[str] = []
    if realized_n < GATE_MIN_CLOSED_TRADES_INFLUENCE_REVIEW:
        tier3_reasons.append(
            f"Realized trades {realized_n} < {GATE_MIN_CLOSED_TRADES_INFLUENCE_REVIEW}"
        )
    if net_cf is None or float(net_cf) <= 0:
        tier3_reasons.append("Net counterfactual GBP not positive on realized subset")
    if decile_lift is None or decile_lift < GATE_MIN_TOP_DECILE_LIFT_PCT:
        tier3_reasons.append(
            f"Top-decile lift {decile_lift} < {GATE_MIN_TOP_DECILE_LIFT_PCT}% required"
        )
    if n_folds < GATE_MIN_WALK_FORWARD_FOLDS:
        tier3_reasons.append(f"Walk-forward folds {n_folds} < {GATE_MIN_WALK_FORWARD_FOLDS}")
    if rl_ope and wis_ess < GATE_MIN_WIS_ESS:
        tier3_reasons.append(f"RL WIS ESS {wis_ess:.0f} < {GATE_MIN_WIS_ESS}")
    tiers.append(
        GateTier(
            tier_id="influence_review",
            label="Influence review",
            passed=tier3_ok and not stop,
            reasons=tier3_reasons + stop,
            requirements={
                "min_closed_trades": GATE_MIN_CLOSED_TRADES_INFLUENCE_REVIEW,
                "min_top_decile_lift_pct": GATE_MIN_TOP_DECILE_LIFT_PCT,
                "min_walk_forward_folds": GATE_MIN_WALK_FORWARD_FOLDS,
            },
        )
    )

    # Tier 4: Live influence (operator sign-off required — never auto-pass)
    tiers.append(
        GateTier(
            tier_id="live_influence",
            label="Live influence (operator sign-off)",
            passed=False,
            reasons=[
                "Requires operator sign-off and Risk-approved wiring",
                f"Minimum {GATE_MIN_CLOSED_TRADES_LIVE_INFLUENCE} closed trades",
            ],
            requirements={"min_closed_trades": GATE_MIN_CLOSED_TRADES_LIVE_INFLUENCE},
        )
    )

    promotion_ready = tiers[2].passed and not stop
    summary = _build_summary(champion, combined, realized_n, promotion_ready, stop)
    return GateReport(tiers=tiers, stop_the_line=stop, promotion_ready=promotion_ready, summary=summary)


def _baseline_big_loser_recall(baselines: dict[str, Any]) -> float | None:
    priors = baselines.get("class_priors") or {}
    if not priors:
        return None
    return float(priors.get("big_loser") or 0.0)


def _top_decile_lift(gbm: dict[str, Any]) -> float | None:
    rows = gbm.get("decile_lift") or []
    if not rows:
        return None
    top = max(rows, key=lambda r: int(r.get("decile") or 0))
    bottom = min(rows, key=lambda r: int(r.get("decile") or 0))
    return float(top.get("mean_ret_30d_pct") or 0) - float(bottom.get("mean_ret_30d_pct") or 0)


def _build_summary(
    champion: dict[str, Any],
    combined: dict[str, Any],
    realized_n: int,
    promotion_ready: bool,
    stop: list[str],
) -> str:
    bad_rate = champion.get("bad_decision_rate_realized")
    net_pnl = champion.get("realized_pnl_gbp_sum")
    saved = combined.get("counterfactual_pnl_gbp_saved")
    missed = combined.get("counterfactual_pnl_gbp_missed")
    net_cf = combined.get("net_counterfactual_gbp")
    parts: list[str] = []
    if bad_rate is not None and realized_n:
        parts.append(
            f"As-is (champion): bad-decision rate {float(bad_rate):.1%} on realized trades (n={realized_n})"
        )
    else:
        parts.append(f"As-is champion evaluated on n={realized_n} realized trades")
    if net_pnl is not None:
        parts.append(f"£{float(net_pnl):.2f} net realized PnL")
    if net_cf is not None:
        parts.append(
            f"Combined challenger net counterfactual £{float(net_cf):.2f} "
            f"(saved £{float(saved or 0):.2f}, missed £{float(missed or 0):.2f})"
        )
    if promotion_ready:
        parts.append("Influence review tier passed — operator sign-off still required for live wiring.")
    elif stop:
        parts.append(f"Stop-the-line: {'; '.join(stop)}")
    else:
        parts.append(
            f"Not promotion-ready: realized n < {GATE_MIN_CLOSED_TRADES_INFLUENCE_REVIEW}. Continue shadow logging."
        )
    return " ".join(p for p in parts if p)
