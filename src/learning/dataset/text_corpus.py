"""Text sidecar builder for Track B (memory, embeddings, graph).

Produces ``text_corpus.parquet`` and ``memory_bundle.jsonl`` keyed by
(cycle_id, ticker, decision_ts). All look-ups respect ``timestamp <= decision_ts``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd
from sqlalchemy.orm import Session

from src.data.models import (
    CycleContextSnapshot,
    GuidanceSnapshot,
    Instrument,
    MacroHeadline,
    MacroSignalLog,
    MacroState,
    ModerationLog,
    OpportunityScoreSnapshot,
    ResearchLog,
    RiskDecision,
    StrategyDecision,
)
from src.learning.spec import TextCorpusSpec, get_text_corpus_spec
from src.utils.logger import get_logger

logger = get_logger("learning.text_corpus")


def _parse_json(value: Any) -> Any:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _doc_id(cycle_id: str, ticker: str, decision_ts: datetime) -> str:
    raw = f"{cycle_id}|{ticker}|{decision_ts.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _concat_body(fields: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(fields.keys()):
        val = fields[key]
        if val in (None, "", [], {}):
            continue
        if isinstance(val, (dict, list)):
            val = json.dumps(val, default=str)
        text = str(val).strip()
        if text:
            parts.append(f"## {key}\n{text}")
    return "\n\n".join(parts)


class TextCorpusBuilder:
    """Build leakage-safe text sidecar rows for memory/graph tracks."""

    def __init__(
        self,
        session: Session,
        spec: TextCorpusSpec | None = None,
        *,
        project_root: Path | None = None,
    ) -> None:
        self.session = session
        self.spec = spec or get_text_corpus_spec()
        self.project_root = project_root or Path(__file__).resolve().parents[3]

    def build(
        self,
        decision_rows: Iterable[Mapping[str, Any]],
        labels_df: pd.DataFrame | None = None,
        *,
        write: bool = True,
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        decision_rows = list(decision_rows)
        if not decision_rows:
            empty = pd.DataFrame()
            return empty, {}

        cycles = {str(r["cycle_id"]) for r in decision_rows}
        tickers = {str(r["ticker"]) for r in decision_rows}

        strategy_by_key = self._load_strategy_text(cycles, tickers)
        moderation_by_key = self._load_moderation_text(cycles, tickers)
        risk_by_key = self._load_risk_text(cycles, tickers)
        research_by_key = self._load_research_text(cycles, tickers)
        opp_reason = self._load_opportunity_reasons(cycles, tickers)
        instruments = self._load_instruments(tickers)
        cycle_context = self._load_cycle_context(cycles)
        guidance_by_cycle = self._load_guidance(cycles)

        label_lookup: dict[tuple[str, str, datetime], dict[str, Any]] = {}
        if labels_df is not None and not labels_df.empty:
            for _, row in labels_df.iterrows():
                ts = row.get("decision_ts")
                if isinstance(ts, pd.Timestamp):
                    ts = ts.to_pydatetime()
                if not isinstance(ts, datetime):
                    continue
                key = (str(row["cycle_id"]), str(row["ticker"]), ts)
                label_lookup[key] = row.to_dict()

        records: list[dict[str, Any]] = []
        for row in decision_rows:
            cycle_id = str(row["cycle_id"])
            ticker = str(row["ticker"])
            decision_ts = row.get("timestamp") or row.get("decision_ts")
            if isinstance(decision_ts, pd.Timestamp):
                decision_ts = decision_ts.to_pydatetime()
            if not isinstance(decision_ts, datetime):
                continue

            strat = strategy_by_key.get((cycle_id, ticker), {})
            mods = moderation_by_key.get((cycle_id, ticker), {})
            risk = risk_by_key.get((cycle_id, ticker), {})
            research = research_by_key.get((cycle_id, ticker), [])
            inst = instruments.get(ticker)
            ctx = cycle_context.get(cycle_id)
            guidance = guidance_by_cycle.get(cycle_id)
            macro = self._macro_at(decision_ts)
            headlines = self._headlines_at(decision_ts, limit=20)
            signals = self._signals_at(decision_ts, limit=15)

            labels = label_lookup.get((cycle_id, ticker, decision_ts), {})

            text_fields = {
                "strategy_reasoning": strat.get("reasoning"),
                "strategy_market_assessment": strat.get("market_assessment"),
                "strategy_portfolio_commentary": strat.get("portfolio_commentary"),
                "strategy_exit_conditions": strat.get("exit_conditions"),
                "strategy_news_sentiment_summary": strat.get("news_sentiment_summary"),
                "strategy_catalysts": strat.get("catalysts"),
                "strategy_risks": strat.get("risks"),
                "gpt_reasoning": mods.get("gpt_reasoning"),
                "gemini_reasoning": mods.get("gemini_reasoning"),
                "risk_reasoning": risk.get("reasoning"),
                "research_entries": research,
                "opportunity_reason": opp_reason.get((cycle_id, ticker)),
                "guidance_rationale": guidance.get("rationale") if guidance else None,
                "guidance_evidence": guidance.get("evidence") if guidance else None,
                "macro_sector_summary": macro.get("sector_summary") if macro else None,
                "macro_economic_highlights": macro.get("economic_highlights") if macro else None,
                "macro_action_plan": macro.get("action_plan") if macro else None,
                "macro_headlines": headlines,
                "macro_signals": signals,
                "instrument_name": inst.name if inst else None,
                "instrument_industry": inst.industry if inst else None,
                "instrument_business_summary": inst.business_summary if inst else None,
                "cycle_context_summary": ctx.get("prompt_guidance_summary") if ctx else None,
                "active_strategy_episode_ids": ctx.get("episode_ids") if ctx else None,
            }

            doc_id = _doc_id(cycle_id, ticker, decision_ts)
            body = _concat_body(text_fields)

            rec = {
                "doc_id": doc_id,
                "cycle_id": cycle_id,
                "ticker": ticker,
                "decision_ts": decision_ts,
                "action": strat.get("action") or row.get("action"),
                "primary_strategy": strat.get("primary_strategy") or row.get("primary_strategy"),
                "conviction": strat.get("conviction") or row.get("conviction"),
                "macro_regime": macro.get("regime") if macro else None,
                "macro_confidence": macro.get("confidence") if macro else None,
                "label_3class": labels.get("label_3class"),
                "realized_pnl_pct": labels.get("realized_pnl_pct"),
                "sector": inst.sector if inst else None,
                **text_fields,
                "body": body,
            }
            records.append(rec)

        df = pd.DataFrame.from_records(records)
        paths: dict[str, str] = {}
        if write and not df.empty:
            paths = self._write(df)
        return df, paths

    def export_memory_jsonl(self, corpus_df: pd.DataFrame) -> str:
        """Write ``memory_bundle.jsonl`` from an in-memory corpus frame."""
        out_path = self.project_root / self.spec.memory_bundle_path()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            for _, row in corpus_df.iterrows():
                doc = {
                    "doc_id": row["doc_id"],
                    "cycle_id": row["cycle_id"],
                    "ticker": row["ticker"],
                    "decision_ts": row["decision_ts"].isoformat()
                    if isinstance(row["decision_ts"], datetime)
                    else str(row["decision_ts"]),
                    "metadata": {
                        "action": row.get("action"),
                        "primary_strategy": row.get("primary_strategy"),
                        "conviction": row.get("conviction"),
                        "macro_regime": row.get("macro_regime"),
                        "label_3class": row.get("label_3class"),
                        "realized_pnl_pct": row.get("realized_pnl_pct"),
                        "sector": row.get("sector"),
                    },
                    "body": row.get("body") or "",
                }
                fh.write(json.dumps(doc, default=str) + "\n")
        return str(out_path)

    def _write(self, df: pd.DataFrame) -> dict[str, str]:
        corpus_path = self.project_root / self.spec.text_corpus_path()
        corpus_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(corpus_path, index=False)
        jsonl_path = self.export_memory_jsonl(df)
        return {"text_corpus": str(corpus_path), "memory_bundle": jsonl_path}

    def _load_strategy_text(self, cycles: set[str], tickers: set[str]) -> dict[tuple[str, str], dict]:
        rows = (
            self.session.query(StrategyDecision)
            .filter(StrategyDecision.cycle_id.in_(cycles), StrategyDecision.ticker.in_(tickers))
            .all()
        )
        out: dict[tuple[str, str], dict] = {}
        for row in rows:
            out[(row.cycle_id, row.ticker)] = {
                "reasoning": row.reasoning,
                "market_assessment": row.market_assessment,
                "portfolio_commentary": row.portfolio_commentary,
                "exit_conditions": row.exit_conditions,
                "news_sentiment_summary": row.news_sentiment_summary,
                "catalysts": _parse_json(row.catalysts_json),
                "risks": _parse_json(row.risks_json),
                "action": row.action,
                "primary_strategy": row.primary_strategy,
                "conviction": row.conviction,
            }
        return out

    def _load_moderation_text(self, cycles: set[str], tickers: set[str]) -> dict[tuple[str, str], dict]:
        rows = (
            self.session.query(ModerationLog)
            .filter(ModerationLog.cycle_id.in_(cycles), ModerationLog.ticker.in_(tickers))
            .all()
        )
        out: dict[tuple[str, str], dict] = {}
        for row in rows:
            entry = out.setdefault((row.cycle_id, row.ticker), {})
            mod = (row.moderator or "").lower()
            if "gpt" in mod:
                entry["gpt_reasoning"] = row.reasoning
            elif "gemini" in mod:
                entry["gemini_reasoning"] = row.reasoning
        return out

    def _load_risk_text(self, cycles: set[str], tickers: set[str]) -> dict[tuple[str, str], dict]:
        rows = (
            self.session.query(RiskDecision)
            .filter(RiskDecision.cycle_id.in_(cycles), RiskDecision.ticker.in_(tickers))
            .all()
        )
        return {(r.cycle_id, r.ticker): {"reasoning": r.reasoning} for r in rows}

    def _load_research_text(self, cycles: set[str], tickers: set[str]) -> dict[tuple[str, str], list]:
        rows = (
            self.session.query(ResearchLog)
            .filter(ResearchLog.cycle_id.in_(cycles), ResearchLog.ticker.in_(tickers))
            .all()
        )
        out: dict[tuple[str, str], list] = {}
        for row in rows:
            out.setdefault((row.cycle_id or "", row.ticker or ""), []).append(
                {
                    "member": row.member,
                    "tool": row.tool_name,
                    "provider": row.provider,
                    "query": row.query,
                    "results": _parse_json(row.results_json),
                }
            )
        return out

    def _load_opportunity_reasons(self, cycles: set[str], tickers: set[str]) -> dict[tuple[str, str], str | None]:
        rows = (
            self.session.query(OpportunityScoreSnapshot)
            .filter(OpportunityScoreSnapshot.cycle_id.in_(cycles), OpportunityScoreSnapshot.ticker.in_(tickers))
            .all()
        )
        return {(r.cycle_id, r.ticker): r.reason for r in rows}

    def _load_instruments(self, tickers: set[str]) -> dict[str, Instrument]:
        rows = self.session.query(Instrument).filter(Instrument.ticker.in_(tickers)).all()
        return {r.ticker: r for r in rows}

    def _load_cycle_context(self, cycles: set[str]) -> dict[str, dict]:
        rows = self.session.query(CycleContextSnapshot).filter(CycleContextSnapshot.cycle_id.in_(cycles)).all()
        out: dict[str, dict] = {}
        for row in rows:
            out[row.cycle_id] = {
                "prompt_guidance_summary": row.prompt_guidance_summary,
                "episode_ids": _parse_json(row.active_strategy_episode_ids_json),
            }
        return out

    def _load_guidance(self, cycles: set[str]) -> dict[str, dict]:
        rows = self.session.query(GuidanceSnapshot).filter(GuidanceSnapshot.cycle_id.in_(cycles)).all()
        out: dict[str, dict] = {}
        for row in rows:
            out[row.cycle_id] = {
                "rationale": row.rationale,
                "evidence": _parse_json(row.evidence_summary_json),
            }
        return out

    def _macro_at(self, decision_ts: datetime) -> dict[str, Any] | None:
        row = (
            self.session.query(MacroState)
            .filter(MacroState.timestamp <= decision_ts)
            .order_by(MacroState.timestamp.desc())
            .first()
        )
        if row is None:
            return None
        payload = _parse_json(row.raw_payload_json) or {}
        return {
            "regime": row.regime,
            "confidence": row.confidence_score,
            "sector_summary": row.sector_summary,
            "economic_highlights": row.economic_highlights,
            "action_plan": _parse_json(row.action_plan_json),
            "vix": payload.get("vix") or payload.get("vix_level"),
            "vix_zscore_60d": payload.get("vix_zscore_60d"),
        }

    def _headlines_at(self, decision_ts: datetime, *, limit: int) -> list[dict]:
        rows = (
            self.session.query(MacroHeadline)
            .filter(MacroHeadline.published_at <= decision_ts)
            .order_by(MacroHeadline.published_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "headline": r.headline,
                "source": r.source,
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "category": r.category,
            }
            for r in rows
        ]

    def _signals_at(self, decision_ts: datetime, *, limit: int) -> list[dict]:
        rows = (
            self.session.query(MacroSignalLog)
            .filter(MacroSignalLog.timestamp <= decision_ts)
            .order_by(MacroSignalLog.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "signal_type": r.signal_type,
                "signal_text": r.signal_text,
                "regime": r.regime,
                "confidence_score": r.confidence_score,
            }
            for r in rows
        ]
