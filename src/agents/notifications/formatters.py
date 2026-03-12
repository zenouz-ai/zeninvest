"""Channel-specific rendering for notification events."""

from datetime import datetime
from typing import Any

from src.agents.notifications.types import NotificationEvent, NotificationMessage


def render_event(
    event: NotificationEvent,
    channel: str,
    *,
    slack_max_chars: int = 3500,
) -> list[NotificationMessage]:
    """Render an event into one or more channel messages."""
    if channel == "slack":
        return _render_slack(event, slack_max_chars=slack_max_chars)
    if channel == "email":
        return _render_email(event)
    return []


def _render_slack(event: NotificationEvent, *, slack_max_chars: int) -> list[NotificationMessage]:
    title = _title_for_event(event)
    prefix = _severity_prefix(event.severity)

    if event.event_type == "cycle_run_summary":
        body = _slack_cycle_summary(event.payload, prefix=prefix)
    elif event.event_type == "trade_instruction_approved":
        body = _slack_trade_instruction(event.payload, prefix=prefix)
    elif event.event_type == "trade_execution_result":
        body = _slack_trade_execution(event.payload, prefix=prefix)
    elif event.event_type == "state_transition":
        body = _slack_state_transition(event.payload, prefix=prefix)
    elif event.event_type == "critical_cycle_failure":
        body = _slack_critical_failure(event.payload, prefix=prefix)
    elif event.event_type == "order_adjustment":
        body = _slack_order_adjustment(event.payload, prefix=prefix)
    else:
        body = _fallback_body(event)

    chunks = _chunk_text(body, max_chars=slack_max_chars)
    return [NotificationMessage(subject=title, body=chunk) for chunk in chunks]


def _render_email(event: NotificationEvent) -> list[NotificationMessage]:
    subject = f"[Investment-Agent][{event.severity.upper()}] {_title_for_event(event)}"
    prefix = _severity_prefix(event.severity)

    if event.event_type == "cycle_run_summary":
        body = _email_cycle_summary(event.payload, prefix=prefix)
    elif event.event_type == "trade_instruction_approved":
        body = _email_trade_instruction(event.payload, prefix=prefix)
    elif event.event_type == "trade_execution_result":
        body = _email_trade_execution(event.payload, prefix=prefix)
    elif event.event_type == "state_transition":
        body = _email_state_transition(event.payload, prefix=prefix)
    elif event.event_type == "critical_cycle_failure":
        body = _email_critical_failure(event.payload, prefix=prefix)
    elif event.event_type == "order_adjustment":
        body = _email_order_adjustment(event.payload, prefix=prefix)
    else:
        body = _fallback_body(event)

    return [NotificationMessage(subject=subject, body=body)]


def _title_for_event(event: NotificationEvent) -> str:
    mapping = {
        "trade_instruction_approved": "Trade Instruction Approved",
        "trade_execution_result": "Trade Execution Result",
        "cycle_run_summary": "Cycle Run Summary",
        "state_transition": "State Transition",
        "critical_cycle_failure": "Critical Cycle Failure",
        "order_adjustment": "Order Adjustment",
    }
    return mapping.get(event.event_type, event.event_type)


def _slack_trade_instruction(payload: dict[str, Any], *, prefix: str) -> str:
    ticker = payload.get("ticker", "N/A")
    action = payload.get("action", "N/A")
    alloc = payload.get("final_allocation_pct") or payload.get("target_allocation_pct")
    qty_display = f"Target: {alloc}% allocation" if alloc is not None else "Target: pending"
    committee = _committee_summary(
        payload.get("moderation_consensus"),
        payload.get("risk_verdict"),
    )
    reasoning = _excerpt(payload.get("reasoning_summary", ""), 300)
    return (
        f"{prefix} [TRADE-INSTRUCTION]\n"
        f"Ticker: {ticker} | Action: {action} | {qty_display}\n"
        f"Committee: {committee}\n"
        f"Conviction: {payload.get('conviction', 'N/A')}\n"
        f"Reasoning: {reasoning or 'N/A'}"
    )


def _slack_trade_execution(payload: dict[str, Any], *, prefix: str) -> str:
    ticker = payload.get("ticker", "N/A")
    action = payload.get("action", "N/A")
    qty = payload.get("quantity")
    qty_display = qty if qty is not None else "N/A"
    execution_status = _display_exec_status(payload.get("execution_status"))
    stop_status = _display_stop_status(payload.get("stop_loss_status"))
    committee = _committee_summary(
        payload.get("moderation_consensus"),
        payload.get("risk_verdict"),
    )
    reasoning = _excerpt(payload.get("reasoning_summary", ""), 250)
    error_msg = _excerpt(payload.get("error_message", ""), 150)
    stop_loss_error = _excerpt(payload.get("stop_loss_error", ""), 150)
    lines = [
        f"{prefix} [TRADE-EXECUTION]",
        f"Ticker: {ticker} | Action: {action} | Qty: {qty_display} | Status: {execution_status}",
        f"Value GBP: {payload.get('value_gbp', 'N/A')} | Stop-loss: {stop_status} ({payload.get('stop_loss_pct', 'N/A')}%)",
        f"Committee: {committee}",
    ]
    if reasoning:
        lines.append(f"Reasoning: {reasoning}")
    if error_msg:
        lines.append(f"Error: {error_msg}")
    if stop_loss_error:
        lines.append(f"Stop-loss error: {stop_loss_error}")
    return "\n".join(lines)


def _slack_state_transition(payload: dict[str, Any], *, prefix: str) -> str:
    return (
        f"{prefix} [STATE]\n"
        f"{payload.get('old_state', 'N/A')} -> {payload.get('new_state', 'N/A')}\n"
        f"Drawdown: {payload.get('drawdown_pct', 'N/A')}\n"
        f"Reason: {_excerpt(payload.get('reason', ''), 200)}"
    )


def _slack_critical_failure(payload: dict[str, Any], *, prefix: str) -> str:
    return (
        f"{prefix} [CRITICAL-FAILURE]\n"
        f"Cycle: {payload.get('cycle_id', 'N/A')}\n"
        f"Stage: {payload.get('stage', 'N/A')} | Type: {payload.get('error_type', 'N/A')}\n"
        f"Error: {_excerpt(payload.get('error_message', ''), 600)}"
    )


def _slack_cycle_summary(payload: dict[str, Any], *, prefix: str) -> str:
    lines: list[str] = []
    lines.append(f"{prefix} [CYCLE-SUMMARY]")
    lines.append(
        f"Cycle: {payload.get('cycle_id', 'N/A')} | Status: {payload.get('status', 'N/A')} | "
        f"Dry-run: {payload.get('dry_run', False)}"
    )
    counts = payload.get("counts", {})
    lines.append(
        "Counts: "
        f"decisions={counts.get('decisions', 0)} "
        f"trades={counts.get('trades', 0)} "
        f"rejected={counts.get('rejected', 0)} "
        f"queued={counts.get('queued', 0)} "
        f"filtered={counts.get('filtered', 0)}"
    )
    lines.append("")
    lines.append("Ticker rows:")

    decisions = payload.get("decisions", [])
    non_hold_rows = [d for d in decisions if str(d.get("action", "")).upper() != "HOLD"]
    hold_count = len(decisions) - len(non_hold_rows)
    rows_for_slack = non_hold_rows if non_hold_rows else decisions

    for d in rows_for_slack:
        ticker = d.get("ticker", "N/A")
        action = d.get("action", "N/A")
        stage = d.get("stage", "N/A")
        qty = d.get("quantity")
        qty_display = qty if qty is not None else "queued"
        exec_status = _display_exec_status(d.get("execution_status"))
        stop_status = _display_stop_status(d.get("stop_loss_status"))
        committee = _committee_summary(d.get("moderation_consensus"), d.get("risk_verdict"))
        reasoning = _excerpt(d.get("strategy_reasoning_excerpt", ""), 120)
        stage_reason = d.get("stage_reason", "")
        lines.append(
            f"- {ticker} {action} | Qty: {qty_display} | Stage: {stage} | {committee}"
        )
        lines.append(f"  Conv={d.get('conviction', 'N/A')} exec={exec_status} stop={stop_status}")
        if stage_reason and stage in ("opportunity_queue", "opportunity_filtered"):
            lines.append(f"  Reason: {stage_reason}")
            if d.get("uov_ewma") is not None or d.get("uov_z") is not None:
                uov_parts = []
                if d.get("uov_ewma") is not None:
                    uov_parts.append(f"uov_ewma={d['uov_ewma']}")
                if d.get("uov_z") is not None:
                    uov_parts.append(f"uov_z={d['uov_z']}")
                lines.append(f"  UOV: {', '.join(uov_parts)}")
        if reasoning:
            lines.append(f"  Reasoning: {reasoning}")

    if hold_count > 0 and non_hold_rows:
        lines.append(f"- (trimmed {hold_count} HOLD rows; see email for full detail)")

    return "\n".join(lines)


def _email_trade_instruction(payload: dict[str, Any], *, prefix: str) -> str:
    return (
        f"{prefix} Trade Instruction Approved\n"
        f"Timestamp UTC: {payload.get('occurred_at', 'N/A')}\n"
        f"Cycle: {payload.get('cycle_id', 'N/A')}\n"
        f"Dry-run: {payload.get('dry_run', False)}\n\n"
        f"Ticker: {payload.get('ticker', 'N/A')}\n"
        f"Action: {payload.get('action', 'N/A')}\n"
        f"Target Allocation %: {payload.get('target_allocation_pct', 'N/A')}\n"
        f"Final Allocation %: {payload.get('final_allocation_pct', 'N/A')}\n"
        f"Conviction: {payload.get('conviction', 'N/A')}\n"
        f"Moderation: {payload.get('moderation_consensus', 'N/A')}\n"
        f"Risk: {payload.get('risk_verdict', 'N/A')}\n"
        f"Reasoning: {payload.get('reasoning_summary', '')}\n"
    )


def _email_trade_execution(payload: dict[str, Any], *, prefix: str) -> str:
    execution_status = _display_exec_status(payload.get("execution_status"))
    stop_status = _display_stop_status(payload.get("stop_loss_status"))
    error_line = payload.get("error_message") or ""
    stop_loss_error = payload.get("stop_loss_error") or ""
    if stop_loss_error:
        error_section = f"Error: {error_line}\nStop-loss error: {stop_loss_error}" if error_line else f"Stop-loss error: {stop_loss_error}"
    else:
        error_section = f"Error: {error_line}"
    return (
        f"{prefix} Trade Execution Result\n"
        f"Timestamp UTC: {payload.get('occurred_at', 'N/A')}\n"
        f"Cycle: {payload.get('cycle_id', 'N/A')}\n"
        f"Dry-run: {payload.get('dry_run', False)}\n\n"
        f"Ticker: {payload.get('ticker', 'N/A')}\n"
        f"Action: {payload.get('action', 'N/A')}\n"
        f"Status: {execution_status}\n"
        f"Quantity: {payload.get('quantity', 'N/A')}\n"
        f"Price: {payload.get('price', 'N/A')}\n"
        f"Value GBP: {payload.get('value_gbp', 'N/A')}\n"
        f"Stop-loss %: {payload.get('stop_loss_pct', 'N/A')}\n"
        f"Stop-loss status: {stop_status}\n"
        f"{error_section}\n"
    )


def _email_state_transition(payload: dict[str, Any], *, prefix: str) -> str:
    return (
        f"{prefix} State Transition\n"
        f"Timestamp UTC: {payload.get('occurred_at', 'N/A')}\n"
        f"Old state: {payload.get('old_state', 'N/A')}\n"
        f"New state: {payload.get('new_state', 'N/A')}\n"
        f"Drawdown %: {payload.get('drawdown_pct', 'N/A')}\n"
        f"Reason: {payload.get('reason', '')}\n"
    )


def _email_critical_failure(payload: dict[str, Any], *, prefix: str) -> str:
    return (
        f"{prefix} Critical Cycle Failure\n"
        f"Timestamp UTC: {payload.get('occurred_at', 'N/A')}\n"
        f"Cycle: {payload.get('cycle_id', 'N/A')}\n"
        f"Stage: {payload.get('stage', 'N/A')}\n"
        f"Error type: {payload.get('error_type', 'N/A')}\n"
        f"Error: {payload.get('error_message', '')}\n"
        f"Trace ID: {payload.get('trace_id', 'N/A')}\n"
    )


def _email_cycle_summary(payload: dict[str, Any], *, prefix: str) -> str:
    lines: list[str] = []
    lines.append(f"{prefix} Cycle Run Summary")
    lines.append(f"Occurred UTC: {payload.get('occurred_at', 'N/A')}")
    lines.append(f"Cycle ID: {payload.get('cycle_id', 'N/A')}")
    lines.append(f"Status: {payload.get('status', 'N/A')}")
    lines.append(f"Dry-run: {payload.get('dry_run', False)}")

    counts = payload.get("counts", {})
    lines.append("")
    lines.append("Counts")
    lines.append(f"- Decisions: {counts.get('decisions', 0)}")
    lines.append(f"- Trades: {counts.get('trades', 0)}")
    lines.append(f"- Rejected: {counts.get('rejected', 0)}")
    lines.append(f"- Queued: {counts.get('queued', 0)}")
    lines.append(f"- Filtered: {counts.get('filtered', 0)}")

    decisions = payload.get("decisions", [])
    if not decisions:
        lines.append("\nNo ticker decisions were available for this run.")
        return "\n".join(lines)

    lines.append("")
    lines.append("Ticker Decision Details")
    for idx, decision in enumerate(decisions, start=1):
        lines.append("")
        lines.append(f"{idx}. {decision.get('ticker', 'N/A')} {decision.get('action', 'N/A')}")
        lines.append(f"   Stage: {decision.get('stage', 'N/A')}")
        if decision.get("stage_reason"):
            lines.append(f"   Reason: {decision.get('stage_reason')}")
        if decision.get("stage") in ("opportunity_queue", "opportunity_filtered") and (
            decision.get("uov_ewma") is not None or decision.get("uov_z") is not None
        ):
            uov_parts = []
            if decision.get("uov_ewma") is not None:
                uov_parts.append(f"uov_ewma={decision['uov_ewma']}")
            if decision.get("uov_z") is not None:
                uov_parts.append(f"uov_z={decision['uov_z']}")
            lines.append(f"   UOV: {', '.join(uov_parts)}")
        lines.append(f"   Conviction: {decision.get('conviction', 'N/A')}")
        lines.append(
            f"   Allocations: target={decision.get('target_allocation_pct', 'N/A')}% "
            f"final={decision.get('final_allocation_pct', 'N/A')}%"
        )
        lines.append(
            f"   Moderation/Risk: {decision.get('moderation_consensus', 'N/A')} / "
            f"{decision.get('risk_verdict', 'N/A')}"
        )
        lines.append(
            f"   Company: industry={decision.get('industry', 'N/A')} | "
            f"market_cap={_fmt_market_cap(decision.get('market_cap'))}"
        )
        lines.append(f"   Description: {_excerpt(decision.get('description_excerpt', ''), 400)}")
        lines.append(
            "   Fundamentals: "
            f"PE={decision.get('trailing_pe', 'N/A')} | "
            f"PB={decision.get('pb_ratio', 'N/A')} | "
            f"ROE={decision.get('roe', 'N/A')} | "
            f"Margin={decision.get('profit_margin', 'N/A')} | "
            f"Debt/Equity={decision.get('debt_equity', 'N/A')} | "
            f"Earnings Growth={decision.get('earnings_growth', 'N/A')}"
        )
        lines.append(f"   News: {_excerpt(decision.get('news_excerpt', ''), 400)}")
        lines.append(f"   Strategy reasoning: {_excerpt(decision.get('strategy_reasoning_excerpt', ''), 300)}")
        lines.append(f"   GPT excerpt: {_excerpt(decision.get('gpt_reasoning_excerpt', ''), 250)}")
        lines.append(f"   Gemini excerpt: {_excerpt(decision.get('gemini_assessment_excerpt', ''), 250)}")
        lines.append(
            f"   Gemini scores: growth={decision.get('gemini_growth_score', 'N/A')} "
            f"risk={decision.get('gemini_risk_score', 'N/A')} "
            f"confidence={decision.get('gemini_confidence_score', 'N/A')}"
        )
        lines.append(
            f"   Execution: status={_display_exec_status(decision.get('execution_status'))} "
            f"qty={decision.get('quantity', 'N/A')} value_gbp={decision.get('value_gbp', 'N/A')}"
        )
        lines.append(
            f"   Stop-loss: pct={decision.get('stop_loss_pct', 'N/A')} "
            f"status={_display_stop_status(decision.get('stop_loss_status'))}"
        )

    return "\n".join(lines)


def _slack_order_adjustment(payload: dict[str, Any], *, prefix: str) -> str:
    adj_type = payload.get("adjustment_type", "N/A")
    lines: list[str] = [f"{prefix} [ORDER-ADJUSTMENT]"]
    lines.append(
        f"Cycle: {payload.get('cycle_id', 'N/A')} | Dry-run: {payload.get('dry_run', False)}"
    )

    adjustments = payload.get("adjustments", [])
    if adjustments:
        lines.append(f"Adjustments: {len(adjustments)}")
        for adj in adjustments:
            old_s = adj.get("old_stop_price", "N/A")
            new_s = adj.get("new_stop_price", "N/A")
            lines.append(
                f"- {adj.get('ticker', 'N/A')} [{adj.get('adjustment_type', adj_type)}] "
                f"stop: {old_s} -> {new_s} (price={adj.get('current_price', 'N/A')}) "
                f"status={adj.get('status', 'N/A')}"
            )
    else:
        lines.append(
            f"{payload.get('ticker', 'N/A')} [{adj_type}] "
            f"stop: {payload.get('old_stop_price', 'N/A')} -> {payload.get('new_stop_price', 'N/A')} "
            f"(price={payload.get('current_price', 'N/A')}) "
            f"status={payload.get('status', 'N/A')}"
        )
    return "\n".join(lines)


def _email_order_adjustment(payload: dict[str, Any], *, prefix: str) -> str:
    lines: list[str] = [f"{prefix} Order Adjustment"]
    lines.append(f"Timestamp UTC: {payload.get('occurred_at', 'N/A')}")
    lines.append(f"Cycle: {payload.get('cycle_id', 'N/A')}")
    lines.append(f"Dry-run: {payload.get('dry_run', False)}")
    lines.append("")

    adjustments = payload.get("adjustments", [])
    if adjustments:
        for idx, adj in enumerate(adjustments, start=1):
            lines.append(f"{idx}. {adj.get('ticker', 'N/A')}")
            lines.append(f"   Type: {adj.get('adjustment_type', 'N/A')}")
            lines.append(f"   Trigger: {adj.get('trigger_reason', 'N/A')}")
            lines.append(
                f"   Stop: {adj.get('old_stop_price', 'N/A')} -> {adj.get('new_stop_price', 'N/A')}"
            )
            lines.append(f"   Current price: {adj.get('current_price', 'N/A')}")
            if adj.get("high_water_mark"):
                lines.append(f"   High-water mark: {adj['high_water_mark']}")
            if adj.get("atr"):
                lines.append(f"   ATR: {adj['atr']}")
            lines.append(f"   Status: {adj.get('status', 'N/A')}")
            lines.append("")
    else:
        lines.append(f"Ticker: {payload.get('ticker', 'N/A')}")
        lines.append(f"Type: {payload.get('adjustment_type', 'N/A')}")
        lines.append(
            f"Stop: {payload.get('old_stop_price', 'N/A')} -> {payload.get('new_stop_price', 'N/A')}"
        )
        lines.append(f"Status: {payload.get('status', 'N/A')}")

    return "\n".join(lines)


def _fallback_body(event: NotificationEvent) -> str:
    return (
        f"Event: {event.event_type}\n"
        f"Cycle: {event.cycle_id or 'N/A'}\n"
        f"Severity: {event.severity}\n"
        f"Occurred: {event.occurred_at.isoformat()}\n"
        f"Payload: {event.payload}"
    )


def _chunk_text(text: str, *, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current and current_len + line_len > max_chars:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append("\n".join(current))

    return chunks or [text]


def _fmt_market_cap(value: Any) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "N/A"

    if num >= 1_000_000_000_000:
        return f"{num / 1_000_000_000_000:.2f}T"
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.2f}B"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.2f}M"
    return f"{num:.0f}"


def _excerpt(text: Any, max_len: int) -> str:
    if text is None:
        return ""
    value = str(text).strip()
    if len(value) <= max_len:
        return value
    return value[: max_len - 3] + "..."


def _severity_prefix(severity: str) -> str:
    sev = str(severity).lower().strip()
    if sev == "critical":
        return "🚨 CRITICAL"
    if sev == "warning":
        return "⚠️ WARN"
    return "ℹ️ INFO"


def _committee_summary(moderation: Any, risk: Any) -> str:
    """Format moderation + risk verdict as committee vote summary.

    For HOLD decisions, moderation and risk are never invoked, so both are None.
    Show "—" instead of "N/A" to indicate "committee not invoked" (refined per US-1.5).
    """
    mod = str(moderation).strip() if moderation else ""
    rsk = str(risk).strip() if risk else ""
    if not mod and not rsk:
        return "—"  # Committee not invoked (e.g. HOLD)
    return f"Moderation={mod or 'N/A'} | Risk={rsk or 'N/A'}"


def _display_exec_status(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return "not_executed"
    return str(value)


def _display_stop_status(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return "not_applicable"
    return str(value)


def format_timestamp_utc(ts: datetime | str | None) -> str:
    """Format timestamp in a compact UTC-friendly form."""
    if ts is None:
        return "N/A"
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(ts)
