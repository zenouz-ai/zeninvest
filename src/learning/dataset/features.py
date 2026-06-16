"""Leakage-safe feature extraction for the trade-outcome learning pipeline.

All features are built from data with ``timestamp <= decision_ts`` for the
row's cycle. Categorical features are kept as strings here — target encoding
happens inside the CV loop (see :mod:`src.learning.models.gbm`).
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timedelta
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from src.data.models import (
    CycleContextSnapshot,
    GuidanceSectorScore,
    GuidanceSnapshot,
    Instrument,
    MacroHeadline,
    MacroSignalLog,
    MacroState,
    MarketDataCache,
    ModerationLog,
    OpportunityQueue,
    OpportunityScoreSnapshot,
    PortfolioSnapshot,
    ResearchLog,
    RiskDecision,
)
from src.utils.logger import get_logger

logger = get_logger("learning.features")

TOP_RISK_RULES: tuple[str, ...] = (
    "max_single_stock",
    "max_sector",
    "correlation",
    "drawdown",
    "vix_limit",
    "daily_loss_halt",
    "cash_floor",
    "min_holding_period",
)


@dataclass
class FeatureRow:
    """Flat feature record for one decision row."""

    cycle_id: str
    ticker: str
    decision_ts: datetime
    features: dict[str, Any]

    def to_record(self) -> dict[str, Any]:
        rec: dict[str, Any] = {
            "cycle_id": self.cycle_id,
            "ticker": self.ticker,
            "decision_ts": self.decision_ts,
        }
        rec.update(self.features)
        return rec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    f = _safe_float(value)
    return int(f) if f is not None else None


def _parse_expected_holding_period(text: str | None) -> float | None:
    """Convert strings like ``"3-6 months"`` or ``"2 weeks"`` into days."""
    if not text:
        return None
    text = str(text).strip().lower()
    if not text:
        return None
    units = {
        "day": 1.0,
        "week": 7.0,
        "month": 30.0,
        "quarter": 90.0,
        "year": 365.0,
    }
    numbers: list[float] = []
    buf = ""
    for ch in text:
        if ch.isdigit() or ch == ".":
            buf += ch
        else:
            if buf:
                try:
                    numbers.append(float(buf))
                except ValueError:
                    pass
                buf = ""
    if buf:
        try:
            numbers.append(float(buf))
        except ValueError:
            pass
    multiplier = 1.0
    for unit, days in units.items():
        if unit in text:
            multiplier = days
            break
    if not numbers:
        return multiplier
    avg = sum(numbers) / len(numbers)
    return avg * multiplier


def _parse_json(value: Any) -> Any:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _json_list_len(value: Any) -> int | None:
    parsed = _parse_json(value) if isinstance(value, str) else value
    if isinstance(parsed, list):
        return len(parsed)
    return None


def _word_count(text: Any) -> int | None:
    if not text or not isinstance(text, str):
        return None
    words = text.split()
    return len(words) if words else 0


def _sector_trend_pct(macro_payload: dict[str, Any], sector: str | None) -> float | None:
    if not sector:
        return None
    intel = macro_payload.get("macro_intelligence")
    if not isinstance(intel, dict):
        intel = macro_payload
    trends = intel.get("sector_trends")
    if not isinstance(trends, dict):
        return None
    for key, value in trends.items():
        if str(key).lower() != str(sector).lower():
            continue
        if isinstance(value, dict):
            return _safe_float(value.get("pct") or value.get("change_pct") or value.get("performance"))
        return _safe_float(value)
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FeatureEngineer:
    """Build a feature matrix for a batch of decision rows.

    The class is stateless beyond the SQLAlchemy session. All look-ups
    respect ``timestamp <= decision_ts`` to avoid leakage. The intent is to
    be readable and conservative; if a piece of data is missing we emit
    ``None``/``NaN`` rather than guess.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        decision_rows: Iterable[Mapping[str, Any]],
        *,
        portfolio_at: dict[str, dict[str, Any]] | None = None,
    ) -> pd.DataFrame:
        """Return a wide feature DataFrame keyed by (cycle_id, ticker)."""
        decision_rows = list(decision_rows)
        if not decision_rows:
            return pd.DataFrame()
        cycles = {str(r["cycle_id"]) for r in decision_rows}
        tickers = {str(r["ticker"]) for r in decision_rows}

        moderation = self._load_moderation(cycles, tickers)
        risk = self._load_risk(cycles, tickers)
        opp = self._load_opportunity(cycles, tickers)
        queue = self._load_queue(tickers)
        instruments = self._load_instruments(tickers)
        research = self._load_research(cycles, tickers)
        cycle_context = self._load_cycle_context(cycles)
        records: list[dict[str, Any]] = []

        for row in decision_rows:
            cycle_id = str(row["cycle_id"])
            ticker = str(row["ticker"])
            decision_ts = row["timestamp"]
            if not isinstance(decision_ts, datetime):
                continue
            features: dict[str, Any] = {}

            self._add_committee_features(features, row, moderation.get((cycle_id, ticker)), risk.get((cycle_id, ticker)))
            self._add_opportunity_macro_features(
                features,
                decision_ts,
                cycle_id,
                opp.get((cycle_id, ticker)),
                queue.get(ticker),
                instruments.get(ticker),
                cycle_context.get(cycle_id),
            )
            self._add_market_fundamentals_features(features, ticker, decision_ts)
            self._add_portfolio_features(features, decision_ts, ticker, instruments.get(ticker), portfolio_at)
            self._add_research_features(features, research.get((cycle_id, ticker), []))
            self._add_attribution_features(features, decision_ts, cycle_context.get(cycle_id))

            records.append(
                FeatureRow(
                    cycle_id=cycle_id,
                    ticker=ticker,
                    decision_ts=decision_ts,
                    features=features,
                ).to_record()
            )

        if not records:
            return pd.DataFrame()
        return pd.DataFrame.from_records(records)

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    def _load_moderation(self, cycles: set[str], tickers: set[str]) -> dict[tuple[str, str], dict[str, Any]]:
        rows = (
            self.session.query(ModerationLog)
            .filter(ModerationLog.cycle_id.in_(cycles), ModerationLog.ticker.in_(tickers))
            .all()
        )
        out: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row.cycle_id, row.ticker)
            entry = out.setdefault(
                key,
                {"moderators": {}, "consensus": None},
            )
            entry["moderators"][row.moderator] = {
                "verdict": row.verdict,
                "growth_score": row.growth_score,
                "risk_score": row.risk_score,
                "confidence_score": row.confidence_score,
                "modifications": _parse_json(row.modifications_json) or {},
            }
            if row.consensus and not entry.get("consensus"):
                entry["consensus"] = row.consensus
        return out

    def _load_risk(self, cycles: set[str], tickers: set[str]) -> dict[tuple[str, str], dict[str, Any]]:
        rows = (
            self.session.query(RiskDecision)
            .filter(RiskDecision.cycle_id.in_(cycles), RiskDecision.ticker.in_(tickers))
            .all()
        )
        out: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            triggered = _parse_json(row.triggered_rules_json) or []
            portfolio = _parse_json(row.portfolio_state_json) or {}
            out[(row.cycle_id, row.ticker)] = {
                "verdict": row.verdict,
                "adjusted_allocation_pct": row.adjusted_allocation_pct,
                "triggered_rules": triggered if isinstance(triggered, list) else [],
                "portfolio_state": portfolio if isinstance(portfolio, dict) else {},
            }
        return out

    def _load_opportunity(self, cycles: set[str], tickers: set[str]) -> dict[tuple[str, str], OpportunityScoreSnapshot]:
        rows = (
            self.session.query(OpportunityScoreSnapshot)
            .filter(OpportunityScoreSnapshot.cycle_id.in_(cycles), OpportunityScoreSnapshot.ticker.in_(tickers))
            .all()
        )
        return {(row.cycle_id, row.ticker): row for row in rows}

    def _load_queue(self, tickers: set[str]) -> dict[str, OpportunityQueue]:
        rows = (
            self.session.query(OpportunityQueue)
            .filter(OpportunityQueue.ticker.in_(tickers))
            .all()
        )
        return {row.ticker: row for row in rows}

    def _load_instruments(self, tickers: set[str]) -> dict[str, Instrument]:
        rows = self.session.query(Instrument).filter(Instrument.ticker.in_(tickers)).all()
        return {row.ticker: row for row in rows}

    def _load_research(self, cycles: set[str], tickers: set[str]) -> dict[tuple[str, str], list[ResearchLog]]:
        rows = (
            self.session.query(ResearchLog)
            .filter(ResearchLog.cycle_id.in_(cycles), ResearchLog.ticker.in_(tickers))
            .all()
        )
        out: dict[tuple[str, str], list[ResearchLog]] = {}
        for row in rows:
            out.setdefault((row.cycle_id or "", row.ticker or ""), []).append(row)
        return out

    def _load_cycle_context(self, cycles: set[str]) -> dict[str, CycleContextSnapshot]:
        rows = self.session.query(CycleContextSnapshot).filter(CycleContextSnapshot.cycle_id.in_(cycles)).all()
        return {row.cycle_id: row for row in rows}

    # ------------------------------------------------------------------
    # Group A — committee
    # ------------------------------------------------------------------

    def _add_committee_features(
        self,
        features: dict[str, Any],
        decision: Mapping[str, Any],
        moderation: dict[str, Any] | None,
        risk: dict[str, Any] | None,
    ) -> None:
        # Strategy fields straight from the decision row.
        features.update(
            {
                "conviction": _safe_float(decision.get("conviction")),
                "target_allocation_pct": _safe_float(decision.get("target_allocation_pct")),
                "risk_parity_target_allocation_pct": _safe_float(decision.get("risk_parity_target_allocation_pct")),
                "risk_parity_trailing_vol_pct": _safe_float(decision.get("risk_parity_trailing_vol_pct")),
                "upside_target_pct": _safe_float(decision.get("upside_target_pct")),
                "stop_loss_pct": _safe_float(decision.get("stop_loss_pct")),
                "expected_holding_period_days": _parse_expected_holding_period(decision.get("expected_holding_period")),
                "growth_potential": str(decision.get("growth_potential")) if decision.get("growth_potential") else None,
                "risk_level": str(decision.get("risk_level")) if decision.get("risk_level") else None,
                "primary_strategy": str(decision.get("primary_strategy")) if decision.get("primary_strategy") else None,
                "decision_action": str(decision.get("action")) if decision.get("action") else None,
                "catalyst_count": _json_list_len(decision.get("catalysts_json")),
                "risk_factor_count": _json_list_len(decision.get("risks_json")),
                "reasoning_word_count": _word_count(decision.get("reasoning")),
            }
        )

        # Moderation aggregates.
        consensus = (moderation or {}).get("consensus")
        moderators = (moderation or {}).get("moderators", {}) if moderation else {}
        gpt = moderators.get("gpt-4o", {})
        gemini = moderators.get("gemini-2.5-flash") or moderators.get("gemini-2.0-flash") or {}
        features.update(
            {
                "gpt_verdict": gpt.get("verdict"),
                "gpt_growth_score": _safe_int(gpt.get("growth_score")),
                "gpt_risk_score": _safe_int(gpt.get("risk_score")),
                "gpt_confidence_score": _safe_int(gpt.get("confidence_score")),
                "gemini_verdict": gemini.get("verdict"),
                "gemini_growth_score": _safe_int(gemini.get("growth_score")),
                "gemini_risk_score": _safe_int(gemini.get("risk_score")),
                "gemini_confidence_score": _safe_int(gemini.get("confidence_score")),
                "moderation_consensus": consensus,
                "consensus_disagreement": int(
                    any((m.get("verdict") or "").upper() == "DISAGREE" for m in moderators.values())
                )
                if moderators
                else None,
            }
        )

        modify_caps = []
        for m in moderators.values():
            mods = m.get("modifications") or {}
            if isinstance(mods, dict):
                cap = _safe_float(mods.get("target_allocation_pct"))
                if cap is not None:
                    modify_caps.append(cap)
        features["modify_cap_pct"] = min(modify_caps) if modify_caps else None

        # Risk fields.
        risk = risk or {}
        triggered = risk.get("triggered_rules") or []
        features["risk_verdict"] = risk.get("verdict")
        features["risk_adjusted_allocation_pct"] = _safe_float(risk.get("adjusted_allocation_pct"))
        features["risk_triggered_rules_count"] = len(triggered) if isinstance(triggered, list) else 0
        portfolio_state = risk.get("portfolio_state") or {}
        if isinstance(portfolio_state, dict):
            features["portfolio_drawdown_pct"] = _safe_float(
                portfolio_state.get("drawdown_pct") or portfolio_state.get("portfolio_drawdown_pct")
            )
        else:
            features["portfolio_drawdown_pct"] = None
        if isinstance(triggered, list):
            features["risk_rule_veto"] = int(
                any(isinstance(r, dict) and r.get("verdict") == "REJECT" for r in triggered)
            )
            rule_names: set[str] = set()
            for item in triggered:
                if isinstance(item, str):
                    rule_names.add(item)
                elif isinstance(item, dict) and item.get("rule_name"):
                    rule_names.add(str(item["rule_name"]))
            for rule in TOP_RISK_RULES:
                features[f"risk_rule_{rule}"] = int(rule in rule_names)
        else:
            features["risk_rule_veto"] = None
            for rule in TOP_RISK_RULES:
                features[f"risk_rule_{rule}"] = None

    # ------------------------------------------------------------------
    # Group B — opportunity, regime, structural
    # ------------------------------------------------------------------

    def _add_opportunity_macro_features(
        self,
        features: dict[str, Any],
        decision_ts: datetime,
        cycle_id: str,
        opp: OpportunityScoreSnapshot | None,
        queue: OpportunityQueue | None,
        instrument: Instrument | None,
        cycle_ctx: CycleContextSnapshot | None,
    ) -> None:
        if opp is not None:
            features.update(
                {
                    "uov_raw": _safe_float(opp.uov_raw),
                    "uov_z": _safe_float(opp.uov_z),
                    "uov_final": _safe_float(opp.uov_final),
                    "uov_ewma": _safe_float(opp.uov_ewma),
                    "uov_previous_ewma": _safe_float(opp.previous_uov_ewma),
                    "uov_ewma_delta": (
                        _safe_float(opp.uov_ewma) - _safe_float(opp.previous_uov_ewma)
                        if opp.previous_uov_ewma is not None and opp.uov_ewma is not None
                        else None
                    ),
                    "momentum_score": _safe_float(opp.momentum_score),
                    "mean_reversion_score": _safe_float(opp.mean_reversion_score),
                    "factor_composite_score": _safe_float(opp.factor_composite_score),
                    "factor_quality_score": _safe_float(opp.factor_quality_score),
                    "factor_value_score": _safe_float(opp.factor_value_score),
                    "news_sentiment_score": _safe_float(opp.news_sentiment_score),
                }
            )
        else:
            for key in [
                "uov_raw",
                "uov_z",
                "uov_final",
                "uov_ewma",
                "uov_previous_ewma",
                "uov_ewma_delta",
                "momentum_score",
                "mean_reversion_score",
                "factor_composite_score",
                "factor_quality_score",
                "factor_value_score",
                "news_sentiment_score",
            ]:
                features[key] = None

        if queue is not None and queue.updated_at and queue.updated_at <= decision_ts:
            features["queued_cycles"] = _safe_int(queue.queued_cycles)
        else:
            features["queued_cycles"] = 0

        # Macro state — latest snapshot with timestamp <= decision_ts.
        macro = (
            self.session.query(MacroState)
            .filter(MacroState.timestamp <= decision_ts)
            .order_by(MacroState.timestamp.desc())
            .first()
        )
        features["macro_regime"] = macro.regime if macro else None
        features["macro_confidence"] = _safe_float(macro.confidence_score) if macro else None

        macro_payload = _parse_json(macro.raw_payload_json) if macro else None
        macro_payload = macro_payload if isinstance(macro_payload, dict) else {}
        features["vix_zscore_60d"] = _safe_float(
            macro_payload.get("vix_zscore_60d") or macro_payload.get("vix_zscore")
        )
        features["vix_level"] = _safe_float(macro_payload.get("vix") or macro_payload.get("vix_level"))
        features["spy_vs_50ma"] = _safe_float(macro_payload.get("spy_vs_50ma"))
        sp200 = macro_payload.get("spy_vs_200ma")
        if sp200 is None and "sp500_above_200ma" in macro_payload:
            sp200 = 1.0 if macro_payload.get("sp500_above_200ma") else -1.0
        features["spy_vs_200ma"] = _safe_float(sp200)

        sector = instrument.sector if instrument else None
        features["sector_trend_pct"] = _sector_trend_pct(macro_payload, sector)

        headline_count = (
            self.session.query(MacroHeadline)
            .filter(
                MacroHeadline.published_at <= decision_ts,
                MacroHeadline.published_at >= decision_ts - timedelta(days=7),
            )
            .count()
        )
        features["macro_headline_count_7d"] = int(headline_count)
        signal_count = (
            self.session.query(MacroSignalLog)
            .filter(
                MacroSignalLog.timestamp <= decision_ts,
                MacroSignalLog.timestamp >= decision_ts - timedelta(days=7),
            )
            .count()
        )
        features["macro_signal_count_7d"] = int(signal_count)

        # Guidance sector score — prefer cycle-aligned snapshot when available.
        if sector:
            guidance = None
            if cycle_ctx is not None and cycle_ctx.guidance_snapshot_id:
                guidance = (
                    self.session.query(GuidanceSnapshot)
                    .filter(GuidanceSnapshot.id == cycle_ctx.guidance_snapshot_id)
                    .first()
                )
            if guidance is None:
                guidance = (
                    self.session.query(GuidanceSnapshot)
                    .filter(GuidanceSnapshot.timestamp <= decision_ts)
                    .order_by(GuidanceSnapshot.timestamp.desc())
                    .first()
                )
            if guidance is not None:
                sector_score = (
                    self.session.query(GuidanceSectorScore)
                    .filter(
                        GuidanceSectorScore.guidance_snapshot_id == guidance.id,
                        GuidanceSectorScore.sector == sector,
                    )
                    .first()
                )
                features["guidance_sector_score"] = _safe_float(sector_score.score) if sector_score else None
                features["guidance_sector_label"] = sector_score.label if sector_score else None
                features["guidance_mode"] = guidance.mode
                features["guidance_snapshot_status"] = guidance.status
            else:
                features["guidance_sector_score"] = None
                features["guidance_sector_label"] = None
                features["guidance_mode"] = None
                features["guidance_snapshot_status"] = None
        else:
            features["guidance_sector_score"] = None
            features["guidance_sector_label"] = None
            features["guidance_mode"] = None
            features["guidance_snapshot_status"] = None

    # ------------------------------------------------------------------
    # Group C — market & fundamentals
    # ------------------------------------------------------------------

    def _add_market_fundamentals_features(
        self,
        features: dict[str, Any],
        ticker: str,
        decision_ts: datetime,
    ) -> None:
        # Last full / lite analysis at or before decision_ts.
        cache_row = (
            self.session.query(MarketDataCache)
            .filter(
                MarketDataCache.ticker == ticker,
                MarketDataCache.timestamp <= decision_ts,
                MarketDataCache.data_type.in_(("full_analysis", "lite_analysis", "indicators", "fundamentals")),
            )
            .order_by(MarketDataCache.timestamp.desc())
            .first()
        )
        payload = _parse_json(cache_row.data_json) if cache_row else None
        payload = payload if isinstance(payload, dict) else {}
        indicators = payload.get("indicators") or {}
        fundamentals = payload.get("fundamentals") or {}

        features.update(
            {
                "rsi_14": _safe_float(indicators.get("rsi")),
                "macd_hist": _safe_float(indicators.get("macd_hist") or indicators.get("macd")),
                "bb_pctb": _safe_float(indicators.get("bb_pctb") or indicators.get("bollinger_pct")),
                "dist_to_50ma": _safe_float(indicators.get("dist_to_50ma")),
                "dist_to_200ma": _safe_float(indicators.get("dist_to_200ma")),
                "obv_slope_10d": _safe_float(indicators.get("obv_slope_10d")),
                "volume_ratio_20d": _safe_float(indicators.get("volume_ratio_20d")),
                "realized_vol_20d": _safe_float(indicators.get("realized_vol_20d")),
                "realized_vol_60d": _safe_float(indicators.get("realized_vol_60d")),
                "atr_pct": _safe_float(indicators.get("atr_pct") or indicators.get("atr")),
                "pe_ratio": _safe_float(fundamentals.get("trailing_pe") or fundamentals.get("pe_ratio")),
                "pb_ratio": _safe_float(fundamentals.get("pb_ratio")),
                "roe": _safe_float(fundamentals.get("roe")),
                "gross_margin": _safe_float(fundamentals.get("gross_margin") or fundamentals.get("profit_margin")),
                "de_ratio": _safe_float(fundamentals.get("debt_equity")),
            }
        )

        # Macro VIX / SPY contextuals from MacroState raw payload (only if dated <= decision_ts).
        macro = (
            self.session.query(MacroState)
            .filter(MacroState.timestamp <= decision_ts)
            .order_by(MacroState.timestamp.desc())
            .first()
        )
        macro_payload = _parse_json(macro.raw_payload_json) if macro else None
        macro_payload = macro_payload if isinstance(macro_payload, dict) else {}
        features["vix_level"] = _safe_float(macro_payload.get("vix") or macro_payload.get("vix_level"))
        features["spy_vs_50ma"] = _safe_float(macro_payload.get("spy_vs_50ma"))
        features["spy_vs_200ma"] = _safe_float(macro_payload.get("spy_vs_200ma"))

    # ------------------------------------------------------------------
    # Group D — portfolio context
    # ------------------------------------------------------------------

    def _add_portfolio_features(
        self,
        features: dict[str, Any],
        decision_ts: datetime,
        ticker: str,
        instrument: Instrument | None,
        portfolio_at: dict[str, dict[str, Any]] | None,
    ) -> None:
        snap_data: dict[str, Any] | None = None
        if portfolio_at:
            # Use the latest provided snapshot at or before decision_ts.
            entries = [
                (key, value)
                for key, value in portfolio_at.items()
                if isinstance(value, dict) and value.get("timestamp") and value["timestamp"] <= decision_ts
            ]
            if entries:
                entries.sort(key=lambda kv: kv[1]["timestamp"], reverse=True)
                snap_data = entries[0][1]
        if snap_data is None:
            snap_row = (
                self.session.query(PortfolioSnapshot)
                .filter(PortfolioSnapshot.timestamp <= decision_ts)
                .order_by(PortfolioSnapshot.timestamp.desc())
                .first()
            )
            if snap_row is not None:
                positions = _parse_json(snap_row.positions_json) or []
                snap_data = {
                    "total_value_gbp": snap_row.total_value_gbp,
                    "cash_gbp": snap_row.cash_gbp,
                    "invested_gbp": snap_row.invested_gbp,
                    "pnl_pct": snap_row.pnl_pct,
                    "num_positions": snap_row.num_positions,
                    "positions": positions if isinstance(positions, list) else [],
                    "timestamp": snap_row.timestamp,
                }
        snap_data = snap_data or {}

        total = _safe_float(snap_data.get("total_value_gbp")) or 0.0
        cash = _safe_float(snap_data.get("cash_gbp")) or 0.0
        positions = snap_data.get("positions") or []
        features["portfolio_total_value_gbp"] = total or None
        features["cash_pct"] = (cash / total * 100.0) if total else None
        features["num_positions"] = _safe_int(snap_data.get("num_positions"))
        features["portfolio_pnl_pct"] = _safe_float(snap_data.get("pnl_pct"))
        pnl = _safe_float(snap_data.get("pnl_pct"))
        features["portfolio_drawdown_from_pnl"] = min(pnl, 0.0) if pnl is not None else None

        # Sector concentration & existing position.
        sector = instrument.sector if instrument else None
        sector_value = 0.0
        ticker_value = 0.0
        ticker_pnl = None
        for pos in positions if isinstance(positions, list) else []:
            if not isinstance(pos, dict):
                continue
            value = _safe_float(pos.get("value_gbp"))
            if value is None:
                continue
            pos_ticker = str(pos.get("ticker") or "")
            pos_sector = pos.get("sector") or (instrument.sector if instrument and pos_ticker == ticker else None)
            if pos_ticker == ticker:
                ticker_value = value
                ticker_pnl = _safe_float(pos.get("pnl_pct"))
            if sector and pos_sector == sector:
                sector_value += value
        features["sector_concentration_pct"] = (sector_value / total * 100.0) if total else None
        features["existing_position_pct"] = (ticker_value / total * 100.0) if total else None
        features["existing_position_pnl_pct"] = ticker_pnl

        # Time since last trade for the same ticker.
        from src.data.models import Order  # local import to avoid cycle

        last_order_ts = (
            self.session.query(Order.timestamp)
            .filter(Order.ticker == ticker, Order.timestamp < decision_ts)
            .order_by(Order.timestamp.desc())
            .first()
        )
        if last_order_ts and last_order_ts[0] is not None:
            delta = decision_ts - last_order_ts[0]
            features["time_since_last_trade_same_ticker_days"] = max(delta.total_seconds() / 86400.0, 0.0)
        else:
            features["time_since_last_trade_same_ticker_days"] = None

    # ------------------------------------------------------------------
    # Group E — research intensity
    # ------------------------------------------------------------------

    def _add_research_features(self, features: dict[str, Any], research_rows: list[ResearchLog]) -> None:
        per_tool: dict[str, int] = {
            "web_search": 0,
            "news_search": 0,
            "sector_search": 0,
            "sec_search": 0,
            "macro_search": 0,
        }
        per_member: dict[str, int] = {}
        cache_hits = 0
        total_cost = 0.0
        for row in research_rows:
            tool = (row.tool_name or "").lower()
            if tool in per_tool:
                per_tool[tool] += 1
            else:
                per_tool[tool] = per_tool.get(tool, 0) + 1
            member = str(row.member or "unknown")
            per_member[member] = per_member.get(member, 0) + 1
            if row.cache_hit:
                cache_hits += 1
            if row.cost_usd:
                try:
                    total_cost += float(row.cost_usd)
                except (TypeError, ValueError):
                    pass
        total = len(research_rows)
        features["research_calls_total"] = total
        for tool, count in per_tool.items():
            features[f"research_{tool}_count"] = count
        for member, count in per_member.items():
            key = member.replace("-", "_").replace(".", "_")
            features[f"research_member_{key}_count"] = count
        features["research_cache_hit_rate"] = (cache_hits / total) if total else None
        features["research_cost_usd"] = total_cost if total else None

    def _add_attribution_features(
        self,
        features: dict[str, Any],
        decision_ts: datetime,
        ctx: CycleContextSnapshot | None,
    ) -> None:
        if ctx is None:
            features["active_episode_count"] = None
            features["guidance_candidate_delta"] = None
            return
        episodes = _parse_json(ctx.active_strategy_episode_ids_json)
        if isinstance(episodes, list):
            features["active_episode_count"] = len(episodes)
        else:
            features["active_episode_count"] = None
        pre = ctx.pre_guidance_candidate_count
        post = ctx.post_guidance_candidate_count
        if pre is not None and post is not None:
            features["guidance_candidate_delta"] = int(post) - int(pre)
        else:
            features["guidance_candidate_delta"] = None

    # ------------------------------------------------------------------
    # Static helper for tests / external auditors
    # ------------------------------------------------------------------

    @staticmethod
    def feature_columns(sample_row: Mapping[str, Any]) -> list[str]:
        return [c for c in sample_row.keys() if c not in {"cycle_id", "ticker", "decision_ts"}]
