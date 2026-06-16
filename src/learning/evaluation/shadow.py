"""Live per-cycle shadow scoring (no influence on execution)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.data.database import get_session
from src.data.models import DecisionShadowScore
from src.learning.evaluation.gbm_inference import predict_gbm_probs
from src.learning.evaluation.policies import DEFAULT_SHADOW_POLICIES, PolicyId, RecommendedAction
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("learning.evaluation.shadow")


class ShadowEvaluator:
    """Score pending BUYs with shadow challenger policies."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def score_cycle(
        self,
        *,
        cycle_id: str,
        pending_buys: list[dict[str, Any]],
        macro_regime: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.settings.learning_shadow_scoring_enabled:
            return []
        if not pending_buys:
            return []

        policy_ids = self._shadow_policies()
        artifact_run_id = self._latest_artifact_run_id()
        results: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        for buy in pending_buys:
            ticker = str(buy.get("ticker") or "")
            decision = buy.get("decision") or {}
            conviction = float(buy.get("conviction") or decision.get("conviction") or 50.0)
            reasoning = str(decision.get("reasoning") or "")
            action = str(buy.get("action") or decision.get("action") or "BUY").upper()
            champion_action: RecommendedAction = "queue" if action == "QUEUED" else "buy"

            for policy_id in policy_ids:
                recommended, scores = self._score_one(
                    policy_id=policy_id,
                    ticker=ticker,
                    conviction=conviction,
                    reasoning=reasoning,
                    macro_regime=macro_regime,
                    buy_context=buy,
                )
                entry = {
                    "cycle_id": cycle_id,
                    "ticker": ticker,
                    "decision_ts": now,
                    "champion_action": champion_action,
                    "policy_id": policy_id.value,
                    "recommended_action": recommended,
                    "scores_json": scores,
                    "artifact_run_ids_json": {"learning_run": artifact_run_id},
                }
                results.append(entry)
                self._persist(entry)

        return results

    def _shadow_policies(self) -> list[PolicyId]:
        raw = self.settings.learning_shadow_policies
        out: list[PolicyId] = []
        for item in raw:
            try:
                out.append(PolicyId(str(item)))
            except ValueError:
                continue
        return out or list(DEFAULT_SHADOW_POLICIES)

    def _gbm_probs(self, buy_context: dict[str, Any], conviction: float) -> dict[str, float]:
        row: dict[str, Any] = {"conviction": conviction}
        decision = buy_context.get("decision") or {}
        if isinstance(decision, dict):
            row.update({k: v for k, v in decision.items() if k != "reasoning"})
        row["target_allocation_pct"] = buy_context.get("target_allocation_pct")
        row["final_allocation_pct"] = buy_context.get("final_allocation_pct")
        try:
            return predict_gbm_probs(row, conviction_fallback=conviction)
        except Exception as exc:
            logger.debug("Shadow GBM inference failed, using heuristic: %s", exc)
            from src.learning.evaluation.gbm_inference import heuristic_probs

            return heuristic_probs(conviction)

    def _score_one(
        self,
        *,
        policy_id: PolicyId,
        ticker: str,
        conviction: float,
        reasoning: str,
        macro_regime: str | None,
        buy_context: dict[str, Any],
    ) -> tuple[RecommendedAction, dict[str, Any]]:
        gbm_veto = float(self.settings.learning_gbm_veto_threshold)
        gbm_prioritize = float(self.settings.learning_gbm_prioritize_threshold)
        mem_veto = float(self.settings.learning_memory_veto_threshold)
        scores: dict[str, Any] = {"conviction": conviction}

        probs = self._gbm_probs(buy_context, conviction)
        p_bl = float(probs.get("big_loser", 0.0))
        p_bw = float(probs.get("big_winner", 0.0))
        p_stall = float(probs.get("stall", 0.0))
        scores["p_big_loser"] = p_bl
        scores["p_big_winner"] = p_bw
        scores["p_stall"] = p_stall
        scores["p_big_loser_heuristic"] = max(0.0, (100.0 - conviction) / 200.0)
        scores["p_big_winner_heuristic"] = min(1.0, conviction / 200.0)

        memory_hits: list[dict[str, Any]] = []
        memory_bad_frac: float | None = None
        if policy_id in (PolicyId.CHALLENGER_MEMORY, PolicyId.CHALLENGER_COMBINED):
            memory_hits = self._memory_hits(ticker, reasoning, macro_regime)
            scores["memory_hits"] = memory_hits
            if memory_hits:
                bad = sum(
                    1
                    for h in memory_hits
                    if str((h.get("metadata") or {}).get("label_3class") or "") in {"big_loser", "stall"}
                )
                memory_bad_frac = bad / len(memory_hits)
                scores["memory_bad_frac"] = memory_bad_frac

        if policy_id == PolicyId.CHALLENGER_GBM:
            if p_bl >= gbm_veto:
                return "skip", scores
            if p_bw >= gbm_prioritize:
                return "prioritize", scores
            return "buy", scores

        if policy_id == PolicyId.CHALLENGER_MEMORY:
            if memory_bad_frac is not None and memory_bad_frac >= mem_veto:
                return "skip", scores
            return "buy", scores

        if policy_id == PolicyId.CHALLENGER_COMBINED:
            if p_bl >= gbm_veto:
                return "skip", scores
            if memory_bad_frac is not None and memory_bad_frac >= mem_veto:
                return "skip", scores
            if p_bw >= gbm_prioritize:
                return "prioritize", scores
            return "buy", scores

        return "buy", scores

    def _memory_hits(
        self,
        ticker: str,
        reasoning: str,
        macro_regime: str | None,
    ) -> list[dict[str, Any]]:
        if not self.settings.learning_embeddings_enabled:
            return self._memory_hits_from_bundle(ticker)
        try:
            from src.learning.memory.retrieval import find_similar_cases

            query = reasoning or f"Trade thesis for {ticker}"
            return find_similar_cases(
                thesis_text=query,
                ticker=ticker,
                regime=macro_regime,
                k=5,
            )
        except Exception as exc:
            logger.debug("Shadow memory retrieval failed: %s", exc)
            return self._memory_hits_from_bundle(ticker)

    def _memory_hits_from_bundle(self, ticker: str) -> list[dict[str, Any]]:
        try:
            from src.learning.evaluation.counterfactual import _load_memory_index, _project_root

            bundle = _load_memory_index(_project_root())
            return [d for d in bundle if str(d.get("ticker") or "") == ticker][:5]
        except Exception:
            return []

    def _latest_artifact_run_id(self) -> str | None:
        from src.data.models import LearningRun

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

    def _persist(self, entry: dict[str, Any]) -> None:
        session = get_session()
        try:
            session.add(
                DecisionShadowScore(
                    cycle_id=entry["cycle_id"],
                    ticker=entry["ticker"],
                    decision_ts=entry["decision_ts"],
                    champion_action=entry["champion_action"],
                    policy_id=entry["policy_id"],
                    recommended_action=entry["recommended_action"],
                    scores_json=json.dumps(entry["scores_json"], default=str),
                    artifact_run_ids_json=json.dumps(entry["artifact_run_ids_json"], default=str),
                )
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.warning("Failed to persist shadow score: %s", exc)
        finally:
            session.close()


def score_cycle_shadow(
    *,
    cycle_id: str,
    pending_buys: list[dict[str, Any]],
    macro_regime: str | None = None,
) -> list[dict[str, Any]]:
    return ShadowEvaluator().score_cycle(
        cycle_id=cycle_id,
        pending_buys=pending_buys,
        macro_regime=macro_regime,
    )
