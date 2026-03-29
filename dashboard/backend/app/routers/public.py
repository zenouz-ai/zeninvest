"""Explicit public dashboard routes with dedicated sanitization."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from src.data.database import get_session
from src.data.models import (
    Instrument,
    MacroHeadline,
    MacroState,
    OpportunityQueue,
    OpportunityScoreSnapshot,
    PortfolioSnapshot,
)
from src.utils.config import get_settings

from ..database import Run, RunDatasetAudit
from ..routers.costs import get_costs_daily, get_costs_monthly
from ..routers.docs import get_doc
from ..routers.performance import get_latest_metrics
from ..schemas import (
    MacroHeadlineSchema,
    PerformanceMetricSchema,
    PublicCostDailySchema,
    PublicCostMonthlySchema,
    PublicMacroStateSchema,
    PublicOpportunityPreviewSchema,
    PublicPortfolioHistoryPointSchema,
    PublicPortfolioPositionSchema,
    PublicPortfolioProtectionSchema,
    PublicPortfolioSectorSchema,
    PublicPortfolioSnapshotSchema,
    PublicRunSummarySchema,
    PublicUniverseItemSchema,
)

router = APIRouter()
settings = get_settings()

_PUBLIC_UNIVERSE_LIMIT = 10
_PUBLIC_PORTFOLIO_POSITIONS_LIMIT = 5
_PUBLIC_RUNS_LIMIT = 5
_PUBLIC_OPPORTUNITY_LIMIT = 5
_PUBLIC_HISTORY_LIMIT = 365
_PORTFOLIO_INDEX_BASE = 100.0


def _safe_json_loads(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _market_cap_bucket(market_cap: float | None) -> str:
    if market_cap is None or market_cap <= 0:
        return "Unavailable"
    if market_cap >= 200_000_000_000:
        return "Mega Cap"
    if market_cap >= 10_000_000_000:
        return "Large Cap"
    if market_cap >= 2_000_000_000:
        return "Mid Cap"
    return "Small Cap"


def _pnl_band(pnl_pct: float | None) -> str:
    value = _coerce_float(pnl_pct, 0.0)
    if value >= 5:
        return "Outperforming"
    if value <= -5:
        return "Underwater"
    return "Range Bound"


def _sanitize_protection_status(status: Any) -> str:
    raw = str(status or "").strip().lower()
    if raw == "protected":
        return "Protected"
    if raw == "eligible":
        return "Needs Lock"
    if raw == "exit_required":
        return "Exit Required"
    return "Inactive"


def _protection_summary(positions: list[dict[str, Any]]) -> PublicPortfolioProtectionSchema:
    summary = PublicPortfolioProtectionSchema()
    for pos in positions:
        label = _sanitize_protection_status(pos.get("profit_lock_status"))
        if label == "Protected":
            summary.protected_count += 1
        elif label == "Needs Lock":
            summary.needs_lock_count += 1
        elif label == "Exit Required":
            summary.exit_required_count += 1
        else:
            summary.inactive_count += 1
    return summary


def _sanitize_public_macro_state(row: MacroState) -> PublicMacroStateSchema:
    top_signals = _safe_json_loads(row.top_signals_json, [])
    action_plan = _safe_json_loads(row.action_plan_json, {})
    safe_action_plan = {
        "summary": action_plan.get("summary"),
        "sector_implications": action_plan.get("sector_implications") or [],
        "risks": action_plan.get("risks") or [],
        "opportunities": action_plan.get("opportunities") or [],
    }
    return PublicMacroStateSchema(
        timestamp=row.timestamp,
        regime=row.regime,
        confidence_score=row.confidence_score,
        top_signals=top_signals if isinstance(top_signals, list) else [],
        action_plan=safe_action_plan,
        sector_summary=row.sector_summary,
        economic_highlights=row.economic_highlights,
    )


def _public_portfolio_positions(
    session: Session,
    positions_data: list[dict[str, Any]],
    total_value_gbp: float,
) -> tuple[list[PublicPortfolioPositionSchema], list[PublicPortfolioSectorSchema]]:
    sectors: dict[str, float] = {}
    position_rows: list[dict[str, Any]] = []
    tickers = [
        (pos.get("instrument") or {}).get("ticker") or pos.get("ticker")
        for pos in positions_data
        if ((pos.get("instrument") or {}).get("ticker") or pos.get("ticker"))
    ]
    instruments = {
        instrument.ticker: instrument
        for instrument in session.query(Instrument).filter(Instrument.ticker.in_(tickers)).all()
    } if tickers else {}

    for pos in positions_data:
        ticker = (pos.get("instrument") or {}).get("ticker") or pos.get("ticker")
        if not ticker:
            continue
        instrument = instruments.get(ticker)
        sector = instrument.sector if instrument else None
        wallet = pos.get("walletImpact") or {}
        value_gbp = _coerce_float(pos.get("value_gbp"))
        if value_gbp <= 0:
            value_gbp = _coerce_float(wallet.get("currentValue"))
        quantity = _coerce_float(pos.get("quantity"))
        if value_gbp <= 0 and quantity > 0:
            value_gbp = quantity * _coerce_float(pos.get("currentPrice"))
        pnl_gbp = _coerce_float(pos.get("pnl_gbp"))
        if pnl_gbp == 0.0:
            pnl_gbp = _coerce_float(wallet.get("unrealizedProfitLoss"))
        pnl_pct = _coerce_float(pos.get("pnl_pct"))
        total_cost = _coerce_float(wallet.get("totalCost"))
        if pnl_pct == 0.0 and total_cost > 0:
            pnl_pct = (pnl_gbp / total_cost) * 100
        allocation_pct = (value_gbp / total_value_gbp * 100) if total_value_gbp > 0 else 0.0
        protection_status = _sanitize_protection_status(pos.get("profit_lock_status"))
        position_rows.append(
            {
                "ticker": ticker,
                "sector": sector,
                "allocation_pct": round(allocation_pct, 2),
                "pnl_band": _pnl_band(pnl_pct),
                "protection_status": protection_status,
                "_value_gbp": value_gbp,
            }
        )
        sectors[sector or "Unknown"] = sectors.get(sector or "Unknown", 0.0) + max(value_gbp, 0.0)

    visible_positions = sorted(position_rows, key=lambda item: item["_value_gbp"], reverse=True)[
        :_PUBLIC_PORTFOLIO_POSITIONS_LIMIT
    ]
    public_positions = [
        PublicPortfolioPositionSchema(
            ticker=row["ticker"],
            sector=row["sector"],
            allocation_pct=row["allocation_pct"],
            pnl_band=row["pnl_band"],
            protection_status=row["protection_status"],
        )
        for row in visible_positions
    ]
    sector_allocations = [
        PublicPortfolioSectorSchema(
            sector=sector,
            allocation_pct=round((value / total_value_gbp * 100), 2) if total_value_gbp > 0 else 0.0,
        )
        for sector, value in sorted(sectors.items(), key=lambda item: item[1], reverse=True)
    ]
    return public_positions, sector_allocations


def _public_run_summary(run: Run, audit_rows: list[RunDatasetAudit]) -> PublicRunSummarySchema:
    summary_json = run.summary_json if isinstance(run.summary_json, dict) else {}
    duration_seconds = summary_json.get("duration_seconds")
    if duration_seconds is None and run.completed_at and run.started_at:
        duration_seconds = (run.completed_at - run.started_at).total_seconds()

    degraded = bool(summary_json.get("audit_summary", {}).get("degraded"))
    if not degraded:
        degraded = any(row.status in {"failed", "partial"} for row in audit_rows)
    audit_status = "degraded" if degraded else "healthy"

    return PublicRunSummarySchema(
        started_at=run.started_at,
        completed_at=run.completed_at,
        run_type=run.run_type,
        status=run.status,
        duration_seconds=_coerce_float(duration_seconds) if duration_seconds is not None else None,
        stocks_screened=summary_json.get("stocks_screened"),
        decisions_made=summary_json.get("decisions_made") or summary_json.get("stocks_reviewed"),
        orders_placed=summary_json.get("orders_placed") or summary_json.get("num_trades"),
        audit_status=audit_status,
        audit_degraded=degraded,
    )


def _score_band(value: float | None) -> str:
    score = _coerce_float(value, 0.0)
    if score >= 2.0:
        return "High Priority"
    if score >= 1.0:
        return "Promising"
    return "Watchlist"


@router.get("/docs/{doc_key}")
async def get_public_doc(doc_key: str):
    """Serve public roadmap / architecture docs."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")
    return await get_doc(doc_key)


@router.get("/costs/daily", response_model=list[PublicCostDailySchema])
async def get_public_costs_daily(
    days: int = Query(default=30, ge=1, le=365),
):
    """Sanitized daily aggregate cost summary."""
    rows = await get_costs_daily(days=days)
    return [
        PublicCostDailySchema(
            date=row.date,
            total_gbp=row.total_gbp + row.api_cost_gbp + row.research_cost_gbp,
            llm_cost_gbp=row.llm_cost_gbp,
            api_cost_gbp=row.api_cost_gbp,
            research_cost_gbp=row.research_cost_gbp,
        )
        for row in rows
    ]


@router.get("/costs/monthly", response_model=list[PublicCostMonthlySchema])
async def get_public_costs_monthly(
    months: int = Query(default=12, ge=1, le=24),
):
    """Sanitized monthly aggregate cost summary."""
    rows = await get_costs_monthly(months=months)
    return [
        PublicCostMonthlySchema(
            year_month=row.year_month,
            total_gbp=row.total_gbp,
            llm_cost_gbp=row.llm_cost_gbp,
            api_cost_gbp=row.api_cost_gbp,
            research_cost_gbp=row.research_cost_gbp,
        )
        for row in rows
    ]


@router.get("/performance/metrics", response_model=PerformanceMetricSchema | None)
async def get_public_performance_metrics():
    """Public aggregate performance snapshot."""
    return await get_latest_metrics()


@router.get("/universe", response_model=list[PublicUniverseItemSchema])
async def get_public_universe(
    limit: int = Query(default=_PUBLIC_UNIVERSE_LIMIT, ge=1, le=_PUBLIC_UNIVERSE_LIMIT),
):
    """Public-safe universe preview."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        rows = (
            session.query(Instrument)
            .order_by(desc(Instrument.last_screened_at))
            .limit(min(limit, _PUBLIC_UNIVERSE_LIMIT))
            .all()
        )
        return [
            PublicUniverseItemSchema(
                ticker=row.ticker,
                name=row.name,
                sector=row.sector,
                industry=row.industry,
                market_cap_bucket=_market_cap_bucket(row.market_cap),
                status="Available" if row.data_available else "Unavailable",
                last_screened_at=row.last_screened_at,
            )
            for row in rows
        ]
    finally:
        session.close()


@router.get("/portfolio", response_model=PublicPortfolioSnapshotSchema | None)
async def get_public_portfolio():
    """Public-safe current portfolio snapshot."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        snapshot = (
            session.query(PortfolioSnapshot)
            .order_by(desc(PortfolioSnapshot.timestamp))
            .first()
        )
        if snapshot is None:
            return None

        positions_data = _safe_json_loads(snapshot.positions_json, [])
        if not isinstance(positions_data, list):
            positions_data = []
        total_value_gbp = _coerce_float(snapshot.total_value_gbp)
        public_positions, sector_allocations = _public_portfolio_positions(
            session,
            positions_data,
            total_value_gbp,
        )
        protection_summary = _protection_summary(positions_data)
        baseline_snapshot = session.query(PortfolioSnapshot).order_by(PortfolioSnapshot.timestamp.asc()).first()
        baseline_value = _coerce_float(baseline_snapshot.total_value_gbp if baseline_snapshot else None, total_value_gbp or 1.0)
        if baseline_value <= 0:
            baseline_value = total_value_gbp or 1.0
        return PublicPortfolioSnapshotSchema(
            timestamp=snapshot.timestamp,
            num_positions=int(snapshot.num_positions or len(positions_data)),
            positions_visible=len(public_positions),
            cash_pct=round((_coerce_float(snapshot.cash_gbp) / total_value_gbp * 100), 2) if total_value_gbp > 0 else 0.0,
            invested_pct=round((_coerce_float(snapshot.invested_gbp) / total_value_gbp * 100), 2) if total_value_gbp > 0 else 0.0,
            value_index=round((total_value_gbp / baseline_value) * _PORTFOLIO_INDEX_BASE, 2) if baseline_value > 0 else _PORTFOLIO_INDEX_BASE,
            pnl_band=_pnl_band(snapshot.pnl_pct),
            positions=public_positions,
            sector_allocations=sector_allocations,
            protection_summary=protection_summary,
        )
    finally:
        session.close()


@router.get("/portfolio/history", response_model=list[PublicPortfolioHistoryPointSchema])
async def get_public_portfolio_history(
    limit: int = Query(default=180, ge=1, le=_PUBLIC_HISTORY_LIMIT),
):
    """Public-safe normalized portfolio history."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        rows = (
            session.query(PortfolioSnapshot)
            .order_by(desc(PortfolioSnapshot.timestamp))
            .limit(min(limit, _PUBLIC_HISTORY_LIMIT))
            .all()
        )
        chronological = list(reversed(rows))
        if not chronological:
            return []
        baseline_value = _coerce_float(chronological[0].total_value_gbp, 1.0)
        if baseline_value <= 0:
            baseline_value = 1.0
        return [
            PublicPortfolioHistoryPointSchema(
                timestamp=row.timestamp,
                value_index=round((_coerce_float(row.total_value_gbp) / baseline_value) * _PORTFOLIO_INDEX_BASE, 2),
            )
            for row in chronological
        ]
    finally:
        session.close()


@router.get("/runs", response_model=list[PublicRunSummarySchema])
async def get_public_runs(
    limit: int = Query(default=_PUBLIC_RUNS_LIMIT, ge=1, le=_PUBLIC_RUNS_LIMIT),
):
    """Public-safe recent run summaries."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        runs = (
            session.query(Run)
            .order_by(desc(Run.started_at))
            .limit(min(limit, _PUBLIC_RUNS_LIMIT))
            .all()
        )
        if not runs:
            return []
        run_ids = [run.id for run in runs]
        audit_rows = (
            session.query(RunDatasetAudit)
            .filter(RunDatasetAudit.run_id.in_(run_ids))
            .all()
        )
        audits_by_run: dict[int, list[RunDatasetAudit]] = {}
        for row in audit_rows:
            audits_by_run.setdefault(row.run_id, []).append(row)
        return [_public_run_summary(run, audits_by_run.get(run.id, [])) for run in runs]
    finally:
        session.close()


@router.get("/opportunity", response_model=list[PublicOpportunityPreviewSchema])
async def get_public_opportunity(
    limit: int = Query(default=_PUBLIC_OPPORTUNITY_LIMIT, ge=1, le=_PUBLIC_OPPORTUNITY_LIMIT),
):
    """Public-safe opportunity preview."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        queue_rows = (
            session.query(OpportunityQueue)
            .order_by(desc(OpportunityQueue.updated_at), desc(OpportunityQueue.last_uov_ewma))
            .limit(_PUBLIC_OPPORTUNITY_LIMIT)
            .all()
        )
        result: list[PublicOpportunityPreviewSchema] = []
        seen: set[str] = set()
        queue_tickers = [row.ticker for row in queue_rows]
        instruments = {
            row.ticker: row
            for row in session.query(Instrument).filter(Instrument.ticker.in_(queue_tickers)).all()
        } if queue_tickers else {}
        for row in queue_rows:
            seen.add(row.ticker)
            instrument = instruments.get(row.ticker)
            result.append(
                PublicOpportunityPreviewSchema(
                    ticker=row.ticker,
                    name=instrument.name if instrument else None,
                    sector=instrument.sector if instrument else None,
                    stage="Queued",
                    action=row.action or "BUY",
                    score_band=_score_band(row.last_uov_ewma),
                    last_updated=row.updated_at,
                )
            )
        if len(result) < min(limit, _PUBLIC_OPPORTUNITY_LIMIT):
            remaining = min(limit, _PUBLIC_OPPORTUNITY_LIMIT) - len(result)
            score_rows = (
                session.query(OpportunityScoreSnapshot)
                .order_by(desc(OpportunityScoreSnapshot.timestamp), desc(OpportunityScoreSnapshot.uov_ewma))
                .limit(50)
                .all()
            )
            score_tickers = [row.ticker for row in score_rows if row.ticker not in seen]
            more_instruments = {
                row.ticker: row
                for row in session.query(Instrument).filter(Instrument.ticker.in_(score_tickers)).all()
            } if score_tickers else {}
            for row in score_rows:
                if row.ticker in seen:
                    continue
                seen.add(row.ticker)
                instrument = more_instruments.get(row.ticker)
                result.append(
                    PublicOpportunityPreviewSchema(
                        ticker=row.ticker,
                        name=instrument.name if instrument else None,
                        sector=instrument.sector if instrument else None,
                        stage="Scored",
                        action=row.action or "WATCH",
                        score_band=_score_band(row.uov_ewma),
                        last_updated=row.timestamp,
                    )
                )
                if len(result) >= min(limit, _PUBLIC_OPPORTUNITY_LIMIT):
                    break
        return result[: min(limit, _PUBLIC_OPPORTUNITY_LIMIT)]
    finally:
        session.close()


@router.get("/macro/state", response_model=PublicMacroStateSchema | None)
async def get_public_macro_state():
    """Public-safe latest macro state."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        row = session.query(MacroState).order_by(desc(MacroState.timestamp)).first()
        if row is None:
            return None
        return _sanitize_public_macro_state(row)
    finally:
        session.close()


@router.get("/macro/state/history", response_model=list[PublicMacroStateSchema])
async def get_public_macro_state_history(
    days: int = Query(default=7, ge=1, le=90),
):
    """Public-safe macro state history."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    session = get_session()
    try:
        rows = (
            session.query(MacroState)
            .filter(MacroState.timestamp >= cutoff)
            .order_by(desc(MacroState.timestamp))
            .all()
        )
        return [_sanitize_public_macro_state(row) for row in rows]
    finally:
        session.close()


@router.get("/macro/headlines", response_model=list[MacroHeadlineSchema])
async def get_public_macro_headlines(
    days: int = Query(default=7, ge=1, le=90),
    category: str = Query(default="all"),
    limit: int = Query(default=200, ge=1, le=500),
):
    """Public read-only macro headline archive."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    session = get_session()
    try:
        query = session.query(MacroHeadline).filter(MacroHeadline.published_at >= cutoff)
        if category and category != "all":
            query = query.filter(MacroHeadline.category == category)
        rows = query.order_by(desc(MacroHeadline.published_at)).limit(limit).all()
        return rows
    finally:
        session.close()


@router.get("/macro/summary")
async def get_public_macro_summary():
    """Public read-only macro summary."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
        latest = session.query(MacroState).order_by(desc(MacroState.timestamp)).first()
        cat_counts_raw = (
            session.query(MacroHeadline.category, func.count(MacroHeadline.id))
            .filter(MacroHeadline.published_at >= cutoff_7d)
            .group_by(MacroHeadline.category)
            .all()
        )
        category_counts = {cat or "general": cnt for cat, cnt in cat_counts_raw}
        total_headlines = sum(category_counts.values())
        top_signal = None
        if latest:
            signals = _safe_json_loads(latest.top_signals_json, [])
            if signals:
                top_signal = signals[0].get("signal_text")
        return {
            "regime": latest.regime if latest else None,
            "confidence_score": latest.confidence_score if latest else None,
            "top_signal": top_signal,
            "headline_count_7d": total_headlines,
            "category_counts": category_counts,
            "last_updated": latest.timestamp.isoformat() if latest else None,
        }
    finally:
        session.close()
