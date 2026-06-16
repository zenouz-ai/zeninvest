"""Completed-trade review helpers for dashboard timeline views."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.agents.execution.order_wallet import (
    effective_filled_shares,
    fifo_wallet_slice,
    quote_fill_price as order_quote_price,
    wallet_per_share_gbp,
    wallet_value_gbp,
)
from src.agents.reporting.outcome_classification import (
    classification_rules_dict,
    derive_label_3class,
    exit_label,
    explain_classification,
    infer_exit_reason,
    simple_result,
    weighted_quote_return_pct,
)
from src.agents.reporting.realized_trades import (
    REALIZED_ORDER_STATUS,
    is_realized_exit_order,
    realized_trade_outcomes_query,
)
from src.backtesting.io import fetch_bars_yfinance
from src.data.models import (
    CycleContextSnapshot,
    DecisionShadowScore,
    GuidanceSectorScore,
    GuidanceSnapshot,
    Instrument,
    MacroHeadline,
    MacroState,
    ModerationLog,
    OpportunityScoreSnapshot,
    Order,
    ResearchLog,
    RiskDecision,
    StopLossAdjustment,
    StrategyDecision,
    TradeOutcome,
)
from src.utils.datetime_utils import ensure_utc_datetime
from src.utils.logger import get_logger
from src.utils.ticker_utils import t212_to_yf

logger = get_logger("trade_review")

PRE_BUY_DAYS = 180
POST_SELL_DAYS = 60
BUY_MATCH_HOURS = 1
SELL_MATCH_HOURS = 2
REASONING_MAX_CHARS = 500
RESEARCH_RESULTS_PREVIEW_CHARS = 1500
PRICE_SERIES_CURRENCY = "USD"
PNL_CURRENCY = "GBP"


@dataclass(frozen=True)
class TimelineWindow:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class FifoBuyLeg:
    """One FIFO-matched buy slice consumed by a closing sell."""

    order: Order
    quantity_matched: float
    value_gbp: float


def build_timeline_window(
    buy_ts: datetime | None,
    sell_ts: datetime,
    *,
    now: datetime | None = None,
) -> TimelineWindow:
    """Return chart window: 6 months pre-buy through min(now, sell + 2 months)."""
    anchor = ensure_utc_datetime(buy_ts) or ensure_utc_datetime(sell_ts)
    if anchor is None:
        anchor = datetime.now(timezone.utc)
    sell_utc = ensure_utc_datetime(sell_ts) or anchor
    current = ensure_utc_datetime(now) or datetime.now(timezone.utc)

    start = anchor - timedelta(days=PRE_BUY_DAYS)
    end = min(current, sell_utc + timedelta(days=POST_SELL_DAYS))
    if end < start:
        end = start
    return TimelineWindow(start=start, end=end)


def match_strategy_decision(
    session: Session,
    ticker: str,
    ts: datetime | None,
    action: str | tuple[str, ...],
    *,
    window_hours: float = BUY_MATCH_HOURS,
) -> StrategyDecision | None:
    """Find the nearest strategy decision for a ticker around an order timestamp."""
    if ts is None:
        return None

    actions = (action,) if isinstance(action, str) else action
    ts_utc = ensure_utc_datetime(ts)
    if ts_utc is None:
        return None
    ts_naive = ts_utc.replace(tzinfo=None)
    delta = timedelta(hours=window_hours)

    rows = (
        session.query(StrategyDecision)
        .filter(
            StrategyDecision.ticker == ticker,
            StrategyDecision.action.in_(actions),
            StrategyDecision.timestamp >= ts_naive - delta,
            StrategyDecision.timestamp <= ts_naive + delta,
        )
        .order_by(desc(StrategyDecision.timestamp))
        .all()
    )
    if not rows:
        return None

    def _distance(row: StrategyDecision) -> float:
        row_ts = ensure_utc_datetime(row.timestamp)
        if row_ts is None:
            return float("inf")
        return abs((row_ts - ts_utc).total_seconds())

    return min(rows, key=_distance)


def truncate_reasoning(text: str | None, max_chars: int = REASONING_MAX_CHARS) -> str | None:
    if not text:
        return None
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[: max_chars - 1].rstrip() + "…"


def _parse_json_dict(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _parse_triggered_rules(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except json.JSONDecodeError:
        pass
    return None


def load_committee_payload(session: Session, cycle_id: str | None, ticker: str) -> dict[str, Any] | None:
    """Strategy + moderation + risk audit for a cycle/ticker."""
    if not cycle_id:
        return None
    strategy = (
        session.query(StrategyDecision)
        .filter(StrategyDecision.cycle_id == cycle_id, StrategyDecision.ticker == ticker)
        .first()
    )
    moderation = (
        session.query(ModerationLog)
        .filter(ModerationLog.cycle_id == cycle_id, ModerationLog.ticker == ticker)
        .order_by(ModerationLog.timestamp)
        .all()
    )
    risk = (
        session.query(RiskDecision)
        .filter(RiskDecision.cycle_id == cycle_id, RiskDecision.ticker == ticker)
        .first()
    )
    if strategy is None and not moderation and risk is None:
        return None

    def _mod_row(row: ModerationLog) -> dict[str, Any]:
        return {
            "moderator": row.moderator,
            "verdict": row.verdict,
            "reasoning": truncate_reasoning(row.reasoning, max_chars=800),
            "growth_score": row.growth_score,
            "risk_score": row.risk_score,
            "confidence_score": row.confidence_score,
            "consensus": row.consensus,
            "modifications": _parse_json_dict(row.modifications_json),
            "prompt_hash": row.prompt_hash,
        }

    consensus = next((m.consensus for m in moderation if m.consensus), None)

    return {
        "cycle_id": cycle_id,
        "ticker": ticker,
        "consensus": consensus,
        "strategy": {
            "action": strategy.action if strategy else None,
            "conviction": strategy.conviction if strategy else None,
            "reasoning": truncate_reasoning(strategy.reasoning if strategy else None, max_chars=800),
            "primary_strategy": strategy.primary_strategy if strategy else None,
        }
        if strategy
        else None,
        "moderation": [_mod_row(m) for m in moderation],
        "risk": {
            "verdict": risk.verdict,
            "adjusted_allocation_pct": risk.adjusted_allocation_pct,
            "proposed_allocation_pct": risk.proposed_allocation_pct,
            "triggered_rules": _parse_triggered_rules(risk.triggered_rules_json),
            "triggered_rules_json": risk.triggered_rules_json,
            "reasoning": truncate_reasoning(risk.reasoning, max_chars=800),
        }
        if risk
        else None,
    }


def load_research_payload(session: Session, cycle_id: str | None, ticker: str) -> dict[str, Any] | None:
    """Agentic research calls for a cycle/ticker."""
    if not cycle_id:
        return None
    rows = (
        session.query(ResearchLog)
        .filter(ResearchLog.cycle_id == cycle_id, ResearchLog.ticker == ticker)
        .order_by(ResearchLog.created_at)
        .all()
    )
    if not rows:
        return {
            "summary": {
                "total_calls": 0,
                "cache_hits": 0,
                "cost_usd": 0.0,
                "by_member": {},
            },
            "calls": [],
        }

    by_member: dict[str, int] = {}
    cache_hits = 0
    total_cost = 0.0
    calls: list[dict[str, Any]] = []
    for row in rows:
        member = str(row.member or "unknown")
        by_member[member] = by_member.get(member, 0) + 1
        if row.cache_hit:
            cache_hits += 1
        if row.cost_usd:
            total_cost += float(row.cost_usd)
        preview = None
        if row.results_json:
            preview = row.results_json[:RESEARCH_RESULTS_PREVIEW_CHARS]
            if len(row.results_json) > RESEARCH_RESULTS_PREVIEW_CHARS:
                preview += "…"
        calls.append(
            {
                "member": member,
                "tool_name": row.tool_name,
                "query": row.query,
                "num_results": row.num_results,
                "provider": row.provider,
                "cache_hit": bool(row.cache_hit),
                "latency_ms": row.latency_ms,
                "cost_usd": row.cost_usd,
                "results_preview": preview,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )

    return {
        "summary": {
            "total_calls": len(rows),
            "cache_hits": cache_hits,
            "cost_usd": round(total_cost, 4),
            "by_member": by_member,
        },
        "calls": calls,
    }


def load_market_context_payload(
    session: Session,
    *,
    cycle_id: str | None,
    ticker: str,
    decision_ts: datetime | None,
) -> dict[str, Any] | None:
    """Macro/guidance/news context at decision time."""
    if decision_ts is None:
        return None
    ts_naive = ensure_utc_datetime(decision_ts)
    if ts_naive is None:
        return None
    ts_cmp = ts_naive.replace(tzinfo=None)

    macro = (
        session.query(MacroState)
        .filter(MacroState.timestamp <= ts_cmp)
        .order_by(desc(MacroState.timestamp))
        .first()
    )
    ctx = (
        session.query(CycleContextSnapshot)
        .filter(CycleContextSnapshot.cycle_id == cycle_id)
        .first()
        if cycle_id
        else None
    )
    instrument = session.query(Instrument).filter(Instrument.ticker == ticker).first()
    sector = instrument.sector if instrument else None

    guidance_score = None
    guidance_label = None
    guidance = None
    if ctx is not None and ctx.guidance_snapshot_id:
        guidance = session.query(GuidanceSnapshot).filter(GuidanceSnapshot.id == ctx.guidance_snapshot_id).first()
    if guidance is None:
        guidance = (
            session.query(GuidanceSnapshot)
            .filter(GuidanceSnapshot.timestamp <= ts_cmp)
            .order_by(desc(GuidanceSnapshot.timestamp))
            .first()
        )
    if guidance is not None and sector:
        sector_row = (
            session.query(GuidanceSectorScore)
            .filter(
                GuidanceSectorScore.guidance_snapshot_id == guidance.id,
                GuidanceSectorScore.sector == sector,
            )
            .first()
        )
        if sector_row:
            guidance_score = sector_row.score
            guidance_label = sector_row.label

    opp = None
    if cycle_id:
        opp = (
            session.query(OpportunityScoreSnapshot)
            .filter(OpportunityScoreSnapshot.cycle_id == cycle_id, OpportunityScoreSnapshot.ticker == ticker)
            .first()
        )

    headlines = (
        session.query(MacroHeadline)
        .filter(MacroHeadline.published_at <= ts_cmp)
        .order_by(desc(MacroHeadline.published_at))
        .limit(3)
        .all()
    )

    shadow_rows = []
    if cycle_id:
        shadow_rows = (
            session.query(DecisionShadowScore)
            .filter(DecisionShadowScore.cycle_id == cycle_id, DecisionShadowScore.ticker == ticker)
            .all()
        )

    return {
        "macro_regime": macro.regime if macro else None,
        "macro_confidence": macro.confidence_score if macro else None,
        "guidance_sector_score": guidance_score,
        "guidance_sector_label": guidance_label,
        "guidance_mode": guidance.mode if guidance else None,
        "news_sentiment_score": opp.news_sentiment_score if opp else None,
        "macro_headlines": [
            {"headline": h.headline, "category": h.category, "source": h.source}
            for h in headlines
        ],
        "guidance_candidate_delta": (
            (ctx.post_guidance_candidate_count - ctx.pre_guidance_candidate_count)
            if ctx is not None
            and ctx.post_guidance_candidate_count is not None
            and ctx.pre_guidance_candidate_count is not None
            else None
        ),
        "shadow_challengers": [
            {
                "policy_id": s.policy_id,
                "recommended_action": s.recommended_action,
                "champion_action": s.champion_action,
            }
            for s in shadow_rows
        ],
    }


def fifo_buy_legs_for_sell(session: Session, sell_order: Order) -> list[FifoBuyLeg]:
    """Replay FIFO matching for a sell and return every buy lot consumed."""
    sell_qty = effective_filled_shares(sell_order)
    if sell_qty <= 0:
        sell_qty = abs(float(sell_order.quantity or 0))
    if sell_qty <= 0:
        return []

    sell_ts_utc = ensure_utc_datetime(sell_order.timestamp)
    if sell_ts_utc is None:
        return []
    sell_cutoff = sell_ts_utc.replace(tzinfo=None)

    buys = (
        session.query(Order)
        .filter(
            Order.ticker == sell_order.ticker,
            Order.action == "BUY",
            Order.status == REALIZED_ORDER_STATUS,
            Order.timestamp < sell_cutoff,
        )
        .order_by(Order.timestamp.asc())
        .all()
    )

    remaining = sell_qty
    legs: list[FifoBuyLeg] = []
    for buy in buys:
        if remaining <= 0:
            break
        buy_qty = effective_filled_shares(buy)
        if buy_qty <= 0:
            buy_qty = float(buy.quantity or 0)
        if buy_qty <= 0:
            continue
        take = min(remaining, buy_qty)
        leg_wallet = fifo_wallet_slice(buy, take)
        if leg_wallet is None:
            buy_wallet = wallet_value_gbp(buy) or float(buy.value_gbp or 0)
            leg_wallet = buy_wallet * (take / buy_qty)
        legs.append(
            FifoBuyLeg(
                order=buy,
                quantity_matched=take,
                value_gbp=leg_wallet,
            )
        )
        remaining -= take
    return legs


def fetch_price_series(
    ticker_t212: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Fetch daily close prices for a T212 ticker over [start, end]."""
    yf_symbol = t212_to_yf(ticker_t212)
    bars = fetch_bars_yfinance([yf_symbol], start, end)
    df = bars.get(yf_symbol)
    if df is None or df.empty:
        return []

    points: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        date_val = row["date"]
        if hasattr(date_val, "strftime"):
            date_str = date_val.strftime("%Y-%m-%d")
        else:
            date_str = str(date_val)[:10]
        close = row.get("close")
        if close is None:
            continue
        try:
            points.append({"date": date_str, "close": round(float(close), 4)})
        except (TypeError, ValueError):
            continue
    return points


def _load_stop_adjustments(session: Session, ticker: str) -> list[dict[str, Any]]:
    rows = (
        session.query(StopLossAdjustment)
        .filter(StopLossAdjustment.ticker == ticker)
        .order_by(StopLossAdjustment.timestamp.asc())
        .all()
    )
    return [
        {
            "timestamp": row.timestamp,
            "trigger_reason": row.trigger_reason,
            "status": row.status,
        }
        for row in rows
    ]


def build_trade_timeline(session: Session, outcome_id: int) -> dict[str, Any] | None:
    """Assemble the full timeline payload for one completed trade."""
    outcome = (
        realized_trade_outcomes_query(session)
        .filter(TradeOutcome.id == outcome_id)
        .first()
    )
    if outcome is None:
        return None

    sell_order = session.query(Order).filter(Order.id == outcome.sell_order_id).first()
    if sell_order is None or not is_realized_exit_order(sell_order):
        return None

    fifo_legs = fifo_buy_legs_for_sell(session, sell_order)
    if not fifo_legs and outcome.buy_order_id:
        fallback = session.query(Order).filter(Order.id == outcome.buy_order_id).first()
        if fallback is not None:
            fifo_legs = [
                FifoBuyLeg(
                    order=fallback,
                    quantity_matched=float(fallback.quantity or 0),
                    value_gbp=float(outcome.buy_value_gbp or fallback.value_gbp or 0),
                )
            ]

    sell_decision = match_strategy_decision(
        session,
        outcome.ticker,
        outcome.sell_timestamp,
        ("SELL", "REDUCE"),
        window_hours=SELL_MATCH_HOURS,
    )

    stop_adjustments = _load_stop_adjustments(session, outcome.ticker)
    stagnation_notes = [
        getattr(leg.order, "warning_note", None)
        for leg in fifo_legs
        if getattr(leg.order, "warning_note", None)
    ]
    buy_warning = stagnation_notes[0] if stagnation_notes else None
    pnl_pct = float(outcome.pnl_pct or 0.0)
    sell_order_type = sell_order.order_type if sell_order else None
    exit_reason = infer_exit_reason(
        sell_timestamp=outcome.sell_timestamp,
        buy_warning_note=buy_warning,
        stop_adjustments=stop_adjustments,
        pnl_pct=pnl_pct,
        sell_order_type=sell_order_type,
    )
    label_3class = derive_label_3class(
        pnl_pct=pnl_pct,
        holding_days=float(outcome.holding_days or 0.0) if outcome.holding_days is not None else None,
        exit_reason=exit_reason,
    )

    earliest_buy_ts = fifo_legs[0].order.timestamp if fifo_legs else outcome.buy_timestamp
    window = build_timeline_window(earliest_buy_ts, outcome.sell_timestamp)
    prices = fetch_price_series(outcome.ticker, window.start, window.end)

    def _iso(dt: datetime | None) -> str | None:
        if dt is None:
            return None
        parsed = ensure_utc_datetime(dt)
        return parsed.isoformat() if parsed else None

    def _buy_leg_payload(leg: FifoBuyLeg, leg_index: int) -> dict[str, Any]:
        order = leg.order
        decision = match_strategy_decision(
            session,
            outcome.ticker,
            order.timestamp,
            "BUY",
            window_hours=BUY_MATCH_HOURS,
        )
        quote = order_quote_price(order)
        per_share_gbp = wallet_per_share_gbp(order)
        if per_share_gbp is None and leg.quantity_matched > 0:
            per_share_gbp = leg.value_gbp / leg.quantity_matched
        return {
            "leg_index": leg_index,
            "order_id": int(order.id),
            "timestamp": _iso(order.timestamp),
            "quantity": round(leg.quantity_matched, 6),
            "price": quote,
            "decision_price": float(order.decision_price) if order.decision_price is not None else None,
            "value_gbp": round(leg.value_gbp, 4),
            "value_gbp_per_share": round(per_share_gbp, 4) if per_share_gbp is not None else None,
            "reasoning": truncate_reasoning(decision.reasoning if decision else None),
            "cycle_id": decision.cycle_id if decision else None,
            "order_type": order.order_type,
            "strategy": order.strategy or (decision.primary_strategy if decision else None),
            "conviction": order.conviction,
            "moderation_result": order.moderation_result,
            "risk_result": order.risk_result,
            "committee": load_committee_payload(
                session,
                decision.cycle_id if decision else None,
                outcome.ticker,
            ),
            "market_context": load_market_context_payload(
                session,
                cycle_id=decision.cycle_id if decision else None,
                ticker=outcome.ticker,
                decision_ts=order.timestamp,
            ),
            "research": load_research_payload(
                session,
                decision.cycle_id if decision else None,
                outcome.ticker,
            ),
        }

    buys_payload = [_buy_leg_payload(leg, idx + 1) for idx, leg in enumerate(fifo_legs)]
    buy_payload = buys_payload[0] if buys_payload else {
        "leg_index": 1,
        "timestamp": _iso(outcome.buy_timestamp),
        "strategy": outcome.strategy,
        "conviction": outcome.conviction,
    }

    sell_filled_qty = effective_filled_shares(sell_order) or abs(float(sell_order.quantity or 0))
    sell_wallet = wallet_value_gbp(sell_order)
    sell_payload: dict[str, Any] = {
        "timestamp": _iso(sell_order.timestamp),
        "price": order_quote_price(sell_order),
        "decision_price": float(sell_order.decision_price)
        if sell_order.decision_price is not None
        else None,
        "value_gbp": round(sell_wallet, 4) if sell_wallet is not None else None,
        "quantity": round(sell_filled_qty, 6),
        "reasoning": truncate_reasoning(sell_decision.reasoning if sell_decision else None),
        "cycle_id": sell_decision.cycle_id if sell_decision else None,
        "order_type": sell_order.order_type,
    }
    sell_per_share = wallet_per_share_gbp(sell_order)
    if sell_per_share is not None:
        sell_payload["value_gbp_per_share"] = round(sell_per_share, 4)
    if sell_decision and sell_decision.cycle_id:
        sell_payload["committee"] = load_committee_payload(session, sell_decision.cycle_id, outcome.ticker)
        sell_payload["market_context"] = load_market_context_payload(
            session,
            cycle_id=sell_decision.cycle_id,
            ticker=outcome.ticker,
            decision_ts=sell_order.timestamp,
        )
        sell_payload["research"] = load_research_payload(session, sell_decision.cycle_id, outcome.ticker)

    quote_legs: list[tuple[float, float]] = []
    for leg in fifo_legs:
        quote = order_quote_price(leg.order)
        if quote is None and leg.order.decision_price is not None:
            quote = float(leg.order.decision_price)
        if quote is not None and leg.quantity_matched > 0:
            quote_legs.append((leg.quantity_matched, quote))
    sell_quote = order_quote_price(sell_order)
    if sell_quote is None and sell_order.decision_price is not None:
        sell_quote = float(sell_order.decision_price)
    quote_return_pct = weighted_quote_return_pct(quote_legs, sell_quote)

    result = simple_result(float(outcome.pnl_pct or 0.0))
    holding_days_val = (
        float(outcome.holding_days or 0.0) if outcome.holding_days is not None else None
    )
    classification_rationale = explain_classification(
        pnl_pct=pnl_pct,
        holding_days=holding_days_val,
        exit_reason=exit_reason,
        label_3class=label_3class,
        result=result,
    )

    return {
        "outcome_id": int(outcome.id),
        "ticker": outcome.ticker,
        "moderation_result": outcome.moderation_result,
        "risk_result": outcome.risk_result,
        "window": {"start": _iso(window.start), "end": _iso(window.end)},
        "prices": prices,
        "price_series_currency": PRICE_SERIES_CURRENCY,
        "pnl_currency": PNL_CURRENCY,
        "classification_rules": classification_rules_dict(),
        "buys": buys_payload,
        "buy": buy_payload,
        "sell": sell_payload,
        "outcome": {
            "pnl_gbp": float(outcome.pnl_gbp or 0.0),
            "pnl_pct": float(outcome.pnl_pct or 0.0),
            "cost_basis_gbp": float(outcome.buy_value_gbp or 0.0),
            "sell_proceeds_gbp": float(outcome.sell_value_gbp or 0.0),
            "holding_days": holding_days_val,
            "result": result,
            "label_3class": label_3class,
            "classification_rationale": classification_rationale,
            "exit_reason": exit_reason,
            "exit_label": exit_label(exit_reason, sell_order_type=sell_order_type),
            "quote_return_pct": round(quote_return_pct, 2) if quote_return_pct is not None else None,
        },
    }
