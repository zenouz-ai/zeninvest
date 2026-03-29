"""Persisted market guidance used to tilt screening and enrich prompts."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc

from src.data.database import get_session
from src.data.models import (
    GuidanceSectorScore,
    GuidanceSnapshot,
    Instrument,
    MacroHeadline,
    MacroSignalLog,
    MacroState,
    OpportunityScoreSnapshot,
    Order,
    TradeOutcome,
)
from src.utils.config import get_settings
from src.utils.fingerprints import stable_hash
from src.utils.logger import get_logger

logger = get_logger("guidance")


POSITIVE_BIAS = {"favored", "positive", "constructive", "bullish", "overweight"}
NEGATIVE_BIAS = {"avoid", "negative", "defensive", "bearish", "underweight"}
RISK_ON_FAVORED = {
    "Technology",
    "Communication Services",
    "Consumer Cyclical",
    "Consumer Discretionary",
    "Industrials",
    "Financial Services",
}
RISK_OFF_FAVORED = {
    "Utilities",
    "Consumer Defensive",
    "Healthcare",
    "Real Estate",
}
RISK_OFF_AVOID = {
    "Technology",
    "Consumer Cyclical",
    "Consumer Discretionary",
    "Communication Services",
}


class GuidanceService:
    """Generate and persist cycle guidance snapshots."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def build_cycle_guidance(self, *, cycle_id: str, cycle_started_at: datetime) -> dict[str, Any] | None:
        """Create and persist a guidance snapshot for one cycle."""
        if not self.settings.guidance_enabled:
            return None

        session = get_session()
        try:
            latest_macro = (
                session.query(MacroState)
                .filter(MacroState.timestamp <= cycle_started_at)
                .order_by(desc(MacroState.timestamp))
                .first()
            )
            if latest_macro is None:
                return None

            freshness_hours = max(
                0.0,
                (cycle_started_at - self._normalize_ts(latest_macro.timestamp)).total_seconds() / 3600.0,
            )
            if freshness_hours > self.settings.guidance_staleness_hours:
                snapshot = GuidanceSnapshot(
                    cycle_id=cycle_id,
                    timestamp=cycle_started_at,
                    mode=self.settings.guidance_mode,
                    status="stale",
                    regime=str(latest_macro.regime),
                    confidence_score=float(latest_macro.confidence_score or 0.0),
                    freshness_hours=freshness_hours,
                    rationale="Macro state is stale; baseline screening retained.",
                    prompt_summary="Persisted macro state is stale; use baseline screening and treat macro context as informational only.",
                    bias_payload_json=json.dumps({"enabled": False, "reason": "stale_macro_state"}),
                    evidence_summary_json=json.dumps({"macro_state_id": latest_macro.id}),
                    raw_payload_json=json.dumps({"macro_state_id": latest_macro.id}),
                )
                session.add(snapshot)
                session.commit()
                return self._serialize_snapshot(snapshot, [])

            sector_scores, evidence = self._compute_sector_scores(session, latest_macro, cycle_started_at)
            rationale = self._build_rationale(latest_macro, sector_scores)
            prompt_summary = self._build_prompt_summary(latest_macro, sector_scores)
            bias_payload = self._build_bias_payload(sector_scores)
            snapshot = GuidanceSnapshot(
                cycle_id=cycle_id,
                timestamp=cycle_started_at,
                mode=self.settings.guidance_mode,
                status="active",
                regime=str(latest_macro.regime),
                confidence_score=float(latest_macro.confidence_score or 0.0),
                freshness_hours=freshness_hours,
                rationale=rationale,
                prompt_summary=prompt_summary,
                bias_payload_json=json.dumps(bias_payload, default=str),
                evidence_summary_json=json.dumps(evidence, default=str),
                raw_payload_json=json.dumps(
                    {
                        "macro_state_id": latest_macro.id,
                        "macro_payload_hash": stable_hash(json.loads(latest_macro.raw_payload_json or "{}")),
                    },
                    default=str,
                ),
            )
            session.add(snapshot)
            session.flush()

            rows: list[GuidanceSectorScore] = []
            for sector, payload in sector_scores.items():
                row = GuidanceSectorScore(
                    guidance_snapshot_id=int(snapshot.id),
                    sector=sector,
                    score=float(payload["score"]),
                    label=str(payload["label"]),
                    rationale=str(payload["rationale"]),
                    evidence_json=json.dumps(payload.get("evidence", []), default=str),
                )
                session.add(row)
                rows.append(row)
            session.commit()
            return self._serialize_snapshot(snapshot, rows)
        except Exception as exc:
            session.rollback()
            logger.warning("Guidance generation failed for %s: %s", cycle_id, exc, exc_info=True)
            failed = GuidanceSnapshot(
                cycle_id=cycle_id,
                timestamp=cycle_started_at,
                mode=self.settings.guidance_mode,
                status="failed",
                regime="NEUTRAL",
                confidence_score=0.0,
                freshness_hours=None,
                rationale=f"Guidance generation failed: {exc}",
                prompt_summary="Guidance unavailable; baseline screening retained.",
                bias_payload_json=json.dumps({"enabled": False, "reason": "generation_failed"}),
                evidence_summary_json=json.dumps({"error": str(exc)}),
                raw_payload_json=json.dumps({}),
            )
            session.add(failed)
            session.commit()
            return self._serialize_snapshot(failed, [])
        finally:
            session.close()

    @staticmethod
    def _normalize_ts(ts: datetime | None) -> datetime:
        if ts is None:
            return datetime.now(timezone.utc)
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts

    def _compute_sector_scores(
        self,
        session: Any,
        latest_macro: MacroState,
        cycle_started_at: datetime,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        scores: dict[str, float] = defaultdict(float)
        rationales: dict[str, list[str]] = defaultdict(list)
        evidence: dict[str, Any] = {
            "macro_state_id": latest_macro.id,
            "macro_signals": [],
            "headline_count_7d": 0,
            "recent_opportunity_window_days": 7,
            "trade_outcome_window_days": 30,
        }

        top_signals = json.loads(latest_macro.top_signals_json or "[]")
        action_plan = json.loads(latest_macro.action_plan_json or "{}")
        sector_implications = action_plan.get("sector_implications", []) or []

        if str(latest_macro.regime) == "RISK_ON":
            for sector in RISK_ON_FAVORED:
                scores[sector] += 0.5
                rationales[sector].append("Risk-on macro regime supports cyclical/growth exposure.")
        elif str(latest_macro.regime) == "RISK_OFF":
            for sector in RISK_OFF_FAVORED:
                scores[sector] += 0.5
                rationales[sector].append("Risk-off macro regime favors defensive sectors.")
            for sector in RISK_OFF_AVOID:
                scores[sector] -= 0.5
                rationales[sector].append("Risk-off macro regime penalizes cyclical/growth sectors.")

        for implication in sector_implications:
            sector = str(implication.get("sector", "")).strip()
            if not sector:
                continue
            bias = str(implication.get("bias", "")).strip().lower()
            if bias in POSITIVE_BIAS:
                scores[sector] += 1.0
            elif bias in NEGATIVE_BIAS:
                scores[sector] -= 1.0
            else:
                scores[sector] += 0.0
            rationale = str(implication.get("rationale", "")).strip()
            if rationale:
                rationales[sector].append(rationale)
            evidence["macro_signals"].append(
                {"sector": sector, "bias": bias, "rationale": rationale}
            )

        macro_signal_rows = (
            session.query(MacroSignalLog)
            .filter(MacroSignalLog.timestamp <= cycle_started_at)
            .order_by(desc(MacroSignalLog.timestamp))
            .limit(10)
            .all()
        )
        evidence["macro_signal_count"] = len(macro_signal_rows)

        cutoff_headlines = cycle_started_at - timedelta(days=7)
        evidence["headline_count_7d"] = (
            session.query(MacroHeadline)
            .filter(
                MacroHeadline.published_at >= cutoff_headlines,
                MacroHeadline.published_at <= cycle_started_at,
            )
            .count()
        )

        cutoff_opps = cycle_started_at - timedelta(days=7)
        opp_rows = (
            session.query(OpportunityScoreSnapshot, Instrument.sector)
            .join(Instrument, Instrument.ticker == OpportunityScoreSnapshot.ticker)
            .filter(
                OpportunityScoreSnapshot.timestamp >= cutoff_opps,
                OpportunityScoreSnapshot.timestamp <= cycle_started_at,
                Instrument.sector.isnot(None),
            )
            .all()
        )
        opp_by_sector: dict[str, list[float]] = defaultdict(list)
        for opp, sector in opp_rows:
            if not sector:
                continue
            opp_by_sector[str(sector)].append(float(opp.uov_final or 0.0))
        for sector, values in opp_by_sector.items():
            avg_score = sum(values) / len(values)
            if avg_score > 0.15:
                scores[sector] += 0.25
                rationales[sector].append("Recent opportunity scores have been relatively strong in this sector.")
            elif avg_score < -0.15:
                scores[sector] -= 0.25
                rationales[sector].append("Recent opportunity scores have been weak in this sector.")

        if self._trade_outcome_count(session, cycle_started_at) >= self.settings.guidance_trade_outcome_min_sample:
            for sector, avg_pnl in self._recent_sector_trade_outcomes(session, cycle_started_at).items():
                if avg_pnl > 1.5:
                    scores[sector] += 0.25
                    rationales[sector].append("Recent closed trades in this sector have been positive.")
                elif avg_pnl < -1.5:
                    scores[sector] -= 0.25
                    rationales[sector].append("Recent closed trades in this sector have been weak.")

        instrument_sectors = {
            str(row[0])
            for row in session.query(Instrument.sector)
            .filter(Instrument.sector.isnot(None), Instrument.sector != "", Instrument.sector != "Unknown")
            .distinct()
            .all()
        }

        result: dict[str, dict[str, Any]] = {}
        for sector in sorted(instrument_sectors | set(scores.keys())):
            score = float(scores.get(sector, 0.0))
            if score >= 0.5:
                label = "favored"
            elif score <= -0.5:
                label = "avoid"
            else:
                label = "neutral"
            result[sector] = {
                "score": round(score, 4),
                "label": label,
                "rationale": " ".join(dict.fromkeys(rationales.get(sector, [])[:3])).strip() or "No strong sector tilt evidence.",
                "evidence": rationales.get(sector, [])[:3],
            }
        return result, evidence

    def _trade_outcome_count(self, session: Any, cycle_started_at: datetime) -> int:
        cutoff = cycle_started_at - timedelta(days=30)
        count = (
            session.query(TradeOutcome)
            .filter(
                TradeOutcome.sell_timestamp >= cutoff,
                TradeOutcome.sell_timestamp <= cycle_started_at,
            )
            .count()
        )
        return int(count or 0)

    def _recent_sector_trade_outcomes(self, session: Any, cycle_started_at: datetime) -> dict[str, float]:
        cutoff = cycle_started_at - timedelta(days=30)
        rows = (
            session.query(TradeOutcome.pnl_pct, Instrument.sector)
            .join(Order, Order.id == TradeOutcome.sell_order_id)
            .join(Instrument, Instrument.ticker == TradeOutcome.ticker)
            .filter(
                TradeOutcome.sell_timestamp >= cutoff,
                TradeOutcome.sell_timestamp <= cycle_started_at,
                Instrument.sector.isnot(None),
            )
            .all()
        )
        buckets: dict[str, list[float]] = defaultdict(list)
        for pnl_pct, sector in rows:
            if sector is None:
                continue
            buckets[str(sector)].append(float(pnl_pct or 0.0))
        return {sector: (sum(values) / len(values)) for sector, values in buckets.items() if values}

    @staticmethod
    def _build_rationale(latest_macro: MacroState, sector_scores: dict[str, dict[str, Any]]) -> str:
        favored = [sector for sector, payload in sector_scores.items() if payload["label"] == "favored"][:3]
        avoid = [sector for sector, payload in sector_scores.items() if payload["label"] == "avoid"][:3]
        parts = [
            f"Regime {latest_macro.regime} with confidence {float(latest_macro.confidence_score or 0.0):.2f}.",
        ]
        if favored:
            parts.append("Favored sectors: " + ", ".join(favored) + ".")
        if avoid:
            parts.append("Avoid sectors: " + ", ".join(avoid) + ".")
        return " ".join(parts)

    @staticmethod
    def _build_prompt_summary(latest_macro: MacroState, sector_scores: dict[str, dict[str, Any]]) -> str:
        favored = [sector for sector, payload in sector_scores.items() if payload["label"] == "favored"][:3]
        avoid = [sector for sector, payload in sector_scores.items() if payload["label"] == "avoid"][:3]
        summary = [
            f"Guidance regime: {latest_macro.regime} ({float(latest_macro.confidence_score or 0.0):.2f} confidence).",
        ]
        if favored:
            summary.append("Lean toward " + ", ".join(favored) + ".")
        if avoid:
            summary.append("Be more selective in " + ", ".join(avoid) + ".")
        return " ".join(summary)

    def _build_bias_payload(self, sector_scores: dict[str, dict[str, Any]]) -> dict[str, Any]:
        favored = [sector for sector, payload in sector_scores.items() if payload["label"] == "favored"]
        avoid = [sector for sector, payload in sector_scores.items() if payload["label"] == "avoid"]
        return {
            "enabled": self.settings.guidance_mode == "active",
            "mode": self.settings.guidance_mode,
            "favored_sectors": favored,
            "avoid_sectors": avoid,
            "sector_caps": {
                sector: (self.settings.candidates_per_sector + 1 if sector in favored else 1 if sector in avoid else self.settings.candidates_per_sector)
                for sector in sector_scores
            },
        }

    @staticmethod
    def _serialize_snapshot(snapshot: GuidanceSnapshot, sector_rows: list[GuidanceSectorScore]) -> dict[str, Any]:
        return {
            "id": int(snapshot.id),
            "cycle_id": snapshot.cycle_id,
            "timestamp": snapshot.timestamp,
            "mode": snapshot.mode,
            "status": snapshot.status,
            "regime": snapshot.regime,
            "confidence_score": float(snapshot.confidence_score or 0.0),
            "freshness_hours": snapshot.freshness_hours,
            "rationale": snapshot.rationale,
            "prompt_summary": snapshot.prompt_summary,
            "bias_payload": json.loads(snapshot.bias_payload_json or "{}"),
            "evidence_summary": json.loads(snapshot.evidence_summary_json or "{}"),
            "sector_scores": [
                {
                    "sector": row.sector,
                    "score": float(row.score or 0.0),
                    "label": row.label,
                    "rationale": row.rationale,
                    "evidence": json.loads(row.evidence_json or "[]"),
                }
                for row in sector_rows
            ],
        }
