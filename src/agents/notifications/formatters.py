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
    elif event.event_type == "trade_without_stop":
        body = _slack_trade_without_stop(event.payload, prefix=prefix)
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
    elif event.event_type == "trade_without_stop":
        body = _email_trade_without_stop(event.payload, prefix=prefix)
    else:
        body = _fallback_body(event)

    return [NotificationMessage(subject=subject, body=body)]


def _title_for_event(event: NotificationEvent) -> str:
    mapping = {
        "trade_instruction_approved": "Trade Decision Status",
        "trade_execution_result": "Trade Execution Status",
        "cycle_run_summary": "Cycle Run Summary",
        "state_transition": "State Transition",
        "critical_cycle_failure": "Critical Cycle Failure",
        "order_adjustment": "Order Adjustment",
        "trade_without_stop": "Trade Without Stop-Loss",
    }
    return mapping.get(event.event_type, event.event_type)


def _display_action(payload: dict[str, Any]) -> Any:
    return payload.get("display_action") or payload.get("action", "N/A")


def _slack_trade_instruction(payload: dict[str, Any], *, prefix: str) -> str:
    ticker = payload.get("ticker", "N/A")
    action = _display_action(payload)
    kind = _trade_decision_heading(payload)
    alloc = payload.get("final_allocation_pct") or payload.get("target_allocation_pct")
    qty_display = f"Target: {alloc}% allocation" if alloc is not None else "Target: pending"
    committee = _committee_summary(
        payload.get("moderation_consensus"),
        payload.get("risk_verdict"),
    )
    reason = _human_reason(
        payload.get("reason_code"),
        fallback=payload.get("reason_detail") or payload.get("reasoning_summary", ""),
        context=payload,
    )
    lines = [
        f"{prefix} [{kind}]",
        f"Ticker: {ticker} | Action: {action} | {qty_display}",
        f"Account: {payload.get('account_label', 'N/A')}",
        f"Committee: {committee}",
        f"Conviction: {payload.get('conviction', 'N/A')}",
    ]
    if reason:
        lines.append(f"Reason: {reason}")
    return "\n".join(lines)


def _slack_trade_execution(payload: dict[str, Any], *, prefix: str) -> str:
    ticker = payload.get("ticker", "N/A")
    action = _display_action(payload)
    qty = payload.get("quantity")
    qty_display = qty if qty is not None else "N/A"
    execution_status = _display_exec_status(payload.get("execution_status"))
    stop_status = _display_stop_status(payload.get("stop_loss_status"))
    heading = _trade_execution_heading(payload)
    committee = _committee_summary(
        payload.get("moderation_consensus"),
        payload.get("risk_verdict"),
    )
    reasoning = _excerpt(payload.get("reasoning_summary", ""), 250)
    reason = _human_reason(
        payload.get("reason_code") or payload.get("error_message"),
        fallback=payload.get("reason_detail") or payload.get("error_message", ""),
        context=payload,
    )
    stop_loss_error = _excerpt(payload.get("stop_loss_error", ""), 150)
    lines = [
        f"{prefix} [{heading}]",
        f"Ticker: {ticker} | Action: {action} | Qty: {qty_display} | Status: {execution_status}",
        f"Account: {payload.get('account_label', 'N/A')} | Value GBP: {payload.get('value_gbp', 'N/A')}",
        f"Stop-loss: {stop_status} ({payload.get('stop_loss_pct', 'N/A')}%) | Committee: {committee}",
    ]
    if payload.get("order_type"):
        lines.insert(2, f"Order type: {payload.get('order_type')}")
    if reason:
        lines.append(f"Reason: {reason}")
    elif reasoning:
        lines.append(f"Reason: {reasoning}")
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
    lines.append(f"Account: {payload.get('account_label', 'N/A')}")
    counts = payload.get("counts", {})
    lines.append(
        "Overview: "
        f"broker_orders_submitted={counts.get('broker_orders_submitted', 0)} "
        f"stop_adjustments={counts.get('stop_adjustments', 0)} "
        f"queued_buys={counts.get('queued', 0)} "
        f"skipped_buys={counts.get('skipped', 0)}"
    )
    lines.append(
        "Counts: "
        f"decisions={counts.get('decisions', 0)} "
        f"trades={counts.get('trades', 0)} "
        f"rejected={counts.get('rejected', 0)} "
        f"queued={counts.get('queued', 0)} "
        f"filtered={counts.get('filtered', 0)} "
        f"risk_rejected={counts.get('risk_rejected', 0)} "
        f"strategy_deferred={counts.get('strategy_deferred', 0)}"
    )
    lines.append("")
    lines.append("Ticker rows:")

    decisions = payload.get("decisions", [])
    non_hold_rows = [d for d in decisions if str(d.get("action", "")).upper() != "HOLD"]
    hold_count = len(decisions) - len(non_hold_rows)
    rows_for_slack = non_hold_rows if non_hold_rows else decisions

    for d in rows_for_slack:
        ticker = d.get("ticker", "N/A")
        action = d.get("display_action") or d.get("action", "N/A")
        status_label = d.get("notification_status") or _summary_status_label(d)
        qty = d.get("quantity")
        qty_display = qty if qty is not None else "queued"
        exec_status = _display_exec_status(d.get("execution_status"))
        stop_status = _display_stop_status(d.get("stop_loss_status"))
        committee = _committee_summary(d.get("moderation_consensus"), d.get("risk_verdict"))
        reason = d.get("notification_reason") or _human_reason(
            d.get("reason_code"),
            fallback=d.get("stage_reason") or d.get("strategy_reasoning_excerpt", ""),
            context=d,
        )
        lines.append(
            f"- {ticker} | {status_label} | Action: {action} | Qty: {qty_display}"
        )
        lines.append(f"  Conv={d.get('conviction', 'N/A')} exec={exec_status} stop={stop_status} | {committee}")
        if reason:
            lines.append(f"  Reason: {reason}")
        if d.get("uov_ewma") is not None or d.get("uov_z") is not None:
            uov_parts = []
            if d.get("uov_ewma") is not None:
                uov_parts.append(f"uov_ewma={d['uov_ewma']}")
            if d.get("uov_z") is not None:
                uov_parts.append(f"uov_z={d['uov_z']}")
            lines.append(f"  UOV: {', '.join(uov_parts)}")

    if hold_count > 0 and non_hold_rows:
        lines.append(f"- (trimmed {hold_count} HOLD rows; see email for full detail)")

    return "\n".join(lines)


def _email_trade_instruction(payload: dict[str, Any], *, prefix: str) -> str:
    return (
        f"{prefix} Trade Decision Status\n"
        f"Timestamp UTC: {payload.get('occurred_at', 'N/A')}\n"
        f"Cycle: {payload.get('cycle_id', 'N/A')}\n"
        f"Dry-run: {payload.get('dry_run', False)}\n\n"
        f"Ticker: {payload.get('ticker', 'N/A')}\n"
        f"Action: {_display_action(payload)}\n"
        f"Account: {payload.get('account_label', 'N/A')}\n"
        f"Notification kind: {payload.get('notification_kind', 'N/A')}\n"
        f"Target Allocation %: {payload.get('target_allocation_pct', 'N/A')}\n"
        f"Final Allocation %: {payload.get('final_allocation_pct', 'N/A')}\n"
        f"Conviction: {payload.get('conviction', 'N/A')}\n"
        f"Moderation: {payload.get('moderation_consensus', 'N/A')}\n"
        f"Risk: {payload.get('risk_verdict', 'N/A')}\n"
        f"Reason: {_human_reason(payload.get('reason_code'), fallback=payload.get('reason_detail') or payload.get('reasoning_summary', ''), context=payload)}\n"
    )


def _email_trade_execution(payload: dict[str, Any], *, prefix: str) -> str:
    execution_status = _display_exec_status(payload.get("execution_status"))
    stop_status = _display_stop_status(payload.get("stop_loss_status"))
    error_line = _human_reason(
        payload.get("reason_code") or payload.get("error_message"),
        fallback=payload.get("reason_detail") or payload.get("error_message") or "",
        context=payload,
    )
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
        f"Action: {_display_action(payload)}\n"
        f"Account: {payload.get('account_label', 'N/A')}\n"
        f"Notification kind: {payload.get('notification_kind', 'N/A')}\n"
        f"Order type: {payload.get('order_type', 'market')}\n"
        f"Status: {execution_status}\n"
        f"Quantity: {payload.get('quantity', 'N/A')}\n"
        f"Price: {payload.get('price', 'N/A')}\n"
        f"Value GBP: {payload.get('value_gbp', 'N/A')}\n"
        f"Stop-loss %: {payload.get('stop_loss_pct', 'N/A')}\n"
        f"Stop-loss status: {stop_status}\n"
        f"Execution note: {payload.get('execution_note', 'N/A')}\n"
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
    lines.append(f"Account: {payload.get('account_label', 'N/A')}")

    counts = payload.get("counts", {})
    lines.append("")
    lines.append("Counts")
    lines.append(f"- Decisions: {counts.get('decisions', 0)}")
    lines.append(f"- Trades: {counts.get('trades', 0)}")
    lines.append(f"- Broker orders submitted: {counts.get('broker_orders_submitted', 0)}")
    lines.append(f"- Stop adjustments: {counts.get('stop_adjustments', 0)}")
    lines.append(f"- Rejected: {counts.get('rejected', 0)}")
    lines.append(f"- Queued: {counts.get('queued', 0)}")
    lines.append(f"- Filtered: {counts.get('filtered', 0)}")
    lines.append(f"- Skipped: {counts.get('skipped', 0)}")
    lines.append(f"- Risk rejected: {counts.get('risk_rejected', 0)}")
    lines.append(f"- Strategy deferred: {counts.get('strategy_deferred', 0)}")

    decisions = payload.get("decisions", [])
    if not decisions:
        lines.append("\nNo ticker decisions were available for this run.")
        return "\n".join(lines)

    lines.append("")
    lines.append("Ticker Decision Details")
    for idx, decision in enumerate(decisions, start=1):
        lines.append("")
        lines.append(f"{idx}. {decision.get('ticker', 'N/A')} {decision.get('display_action') or decision.get('action', 'N/A')}")
        lines.append(f"   Status: {decision.get('notification_status') or _summary_status_label(decision)}")
        reason = decision.get("notification_reason") or _human_reason(
            decision.get("reason_code"),
            fallback=decision.get("stage_reason") or decision.get("strategy_reasoning_excerpt", ""),
            context=decision,
        )
        if reason:
            lines.append(f"   Reason: {reason}")
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


def _slack_trade_without_stop(payload: dict[str, Any], *, prefix: str) -> str:
    ticker = payload.get("ticker", "N/A")
    qty = payload.get("quantity", "N/A")
    price = payload.get("price", "N/A")
    stop_pct = payload.get("stop_loss_pct", "N/A")
    error = _excerpt(payload.get("error_message", ""), 200)
    return (
        f"{prefix} [TRADE-WITHOUT-STOP]\n"
        f"Ticker: {ticker} | Qty: {qty} | Price: {price}\n"
        f"Stop-loss %: {stop_pct}\n"
        f"Error: {error}\n"
        f"ACTION REQUIRED: Position has no stop-loss protection. "
        f"Check place_missing_stops on next cycle or manually place stop."
    )


def _email_trade_without_stop(payload: dict[str, Any], *, prefix: str) -> str:
    return (
        f"{prefix} Trade Without Stop-Loss\n"
        f"Timestamp UTC: {payload.get('occurred_at', 'N/A')}\n"
        f"Cycle: {payload.get('cycle_id', 'N/A')}\n"
        f"Dry-run: {payload.get('dry_run', False)}\n\n"
        f"Ticker: {payload.get('ticker', 'N/A')}\n"
        f"Action: {payload.get('action', 'N/A')}\n"
        f"Quantity: {payload.get('quantity', 'N/A')}\n"
        f"Price: {payload.get('price', 'N/A')}\n"
        f"Stop-loss %: {payload.get('stop_loss_pct', 'N/A')}\n"
        f"Error: {payload.get('error_message', 'N/A')}\n\n"
        f"ACTION REQUIRED: This position has no stop-loss protection.\n"
        f"The next cycle's place_missing_stops() should auto-place the stop,\n"
        f"but verify manually if this is a live position.\n"
    )


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


def _trade_decision_heading(payload: dict[str, Any]) -> str:
    kind = str(payload.get("notification_kind", "")).strip().lower()
    return {
        "buy_queued": "BUY-QUEUED",
        "buy_skipped": "BUY-SKIPPED",
        "risk_rejected": "RISK-REJECTED",
    }.get(kind, "TRADE-DECISION")


def _trade_execution_heading(payload: dict[str, Any]) -> str:
    kind = str(payload.get("notification_kind", "")).strip().lower()
    if kind:
        return {
            "order_submitted": "ORDER-SUBMITTED",
            "buy_skipped": "BUY-SKIPPED",
            "order_skipped": "ORDER-SKIPPED",
            "order_failed": "ORDER-FAILED",
        }.get(kind, "TRADE-EXECUTION")
    status = str(payload.get("execution_status", "")).strip().lower()
    if status in {"filled", "pending", "dry_run", "placed"}:
        return "ORDER-SUBMITTED"
    if status == "skipped":
        return "BUY-SKIPPED" if str(payload.get("action", "")).upper() == "BUY" else "ORDER-SKIPPED"
    if status == "failed":
        return "ORDER-FAILED"
    return "TRADE-EXECUTION"


def _summary_status_label(decision: dict[str, Any]) -> str:
    status = str(decision.get("execution_status", "")).strip().lower()
    stage = str(decision.get("stage", "")).strip().lower()
    if status in {"filled", "pending", "dry_run", "placed"}:
        return "Submitted"
    if status == "skipped" or stage in {"execution_skipped", "cash_floor_guard"}:
        return "Skipped"
    if status == "failed":
        return "Rejected"
    if stage == "opportunity_queue":
        return "Queued for next cycle"
    if stage == "opportunity_filtered":
        return "Filtered out"
    if stage in {"risk", "risk_reject"}:
        return "Rejected"
    if stage in {"strategy_hold", "strategy_queued"}:
        return "Held"
    return "Held"


def _human_reason(reason_code: Any, *, fallback: Any = "", context: dict[str, Any] | None = None) -> str:
    code = str(reason_code or "").strip().lower()
    ctx = context or {}
    if code == "below_min_order_value":
        value = ctx.get("value_gbp")
        min_order = ctx.get("min_order_gbp", 500)
        try:
            return f"Target order value GBP {float(value):.2f} is below minimum GBP {float(min_order):.2f}"
        except (TypeError, ValueError):
            return "Target order value is below the configured minimum order size"
    if code == "no_price":
        return "No current price was available, so no order was sent"
    if code == "target_already_met":
        return "Target allocation was already met, so no order was sent"
    if code == "below_min_reduce_pct":
        threshold = ctx.get("min_reduce_pct")
        if threshold is not None:
            return f"Requested trim is below the minimum reduce threshold of {threshold}%"
        return "Requested trim is below the minimum reduce threshold"
    if code == "awaiting_promotion":
        return "Approved buy is queued until it survives a second cycle"
    if code == "capacity_gated":
        return "Approved buy is queued because there is no slot or cash available this cycle"
    if code == "below_immediate":
        return "Approved buy stayed in the queue because it is below the immediate execution threshold"
    if code == "below_queue":
        return "Candidate was filtered out because its UOV score is below the queue threshold"
    if code == "queue_expired":
        return "Candidate was removed from the queue after exceeding the queue lifetime"
    if code == "no_longer_eligible":
        return "Candidate was removed from the queue because it no longer qualified"
    if code == "cash_floor_guard":
        return "No order was sent because available cash would have fallen below the cash floor"
    if code in {"reduce_guardrail_no_gain_or_risk", "reduce_guardrail_below_profit_floor"}:
        return "Held instead of reducing because the position has not reached the required profit threshold"
    if code == "reduce_guardrail_invalid_trigger":
        return "Held instead of reducing because REDUCE is reserved for rare profit trims only"
    if code == "reduce_guardrail_invalid_tier":
        return "Held instead of reducing because only 50% trims are allowed"
    if code == "sell_guardrail_below_profit_floor":
        return "Held instead of selling because unrealized profit has not reached the sell threshold"
    if code == "sell_guardrail_invalid_trigger":
        return "Held instead of selling because there was no valid hard-exit or gain-realization trigger"
    if code == "take_profit_full_sell":
        return "Profit-lock policy triggered a full SELL after the target profit threshold was reached"
    if code == "small_position_cleanup":
        return "Full SELL triggered because the holding fell below the small-position cleanup threshold"
    if code == "profit_lock_stop_placed":
        return "Broker stop protection was placed to lock at least the target profit"
    if code == "profit_lock_stop_already_sufficient":
        return "Existing broker stop already locks at least the target profit"
    if code == "profit_lock_unprotected_exit":
        return "Full SELL triggered because the position could not be protected at the profit-lock threshold"
    if code == "profit_lock_hold_blocked":
        return "Held was disallowed because the position was above the profit threshold without qualifying stop protection"
    if code == "profit_lock_remainder_unprotected":
        return "REDUCE was converted to full SELL because the remaining shares could not be profit-locked"
    if code == "risk_rejected":
        text = _excerpt(fallback, 180)
        return text or "Risk rules rejected this trade"
    if code == "execution_failed":
        text = _excerpt(fallback, 180)
        return text or "Order submission failed"
    if code == "strategy_deferred":
        text = _excerpt(fallback, 160)
        return text or "Strategy deferred this ticker before moderation and risk review"
    return _excerpt(fallback, 180)


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


# --- Slack Trade Command Reply Formatters (US-1.6) ---


def format_trade_command_reply(result: "SingleTickerResult") -> str:
    """Format a Slack command result for Slack thread reply.

    Args:
        result: Shared Slack command result object.
    """
    ticker = result.ticker_yf or result.ticker_t212

    if result.user_action == "CANCEL" or result.command_kind == "cancel":
        return _format_cancel_reply(result)
    if result.status == "review_only":
        return _format_review_reply(result, ticker)
    elif result.status == "partial":
        return _format_partial_reply(result, ticker)
    elif result.status == "executed":
        return _format_executed_reply(result, ticker)
    elif result.status == "rejected":
        return _format_rejected_reply(result, ticker)
    else:
        return _format_error_reply(result, ticker)


def _mode_label(result: "SingleTickerResult") -> str:
    mode = (result.execution_mode or "").lower()
    if mode == "strategy":
        if result.user_action == "REVIEW":
            return "strategy review"
        return "strategy-triggered trade"
    if mode == "direct":
        return "direct trade"
    if mode == "cancel_only":
        return "cancel command"
    return mode or "unspecified"


def _format_review_reply(result: "SingleTickerResult", ticker: str) -> str:
    """Format REVIEW response with full pipeline details."""
    lines = [f"*Review {ticker}*"]
    lines.append(f"Mode: {_mode_label(result)}")

    # Price
    if result.price:
        lines.append(f"Price: ${result.price:.2f}")

    # Strategy
    if result.strategy_decision:
        action = result.strategy_action or "HOLD"
        conv = result.conviction
        alloc = result.strategy_decision.get("target_allocation_pct", "—")
        stop = result.strategy_decision.get("stop_loss_pct", "—")
        lines.append(f"\n*Strategy:* {action} (conviction {conv})")
        lines.append(f"Allocation: {alloc}% | Stop-loss: {stop}%")

        reasoning = result.strategy_decision.get("reasoning", "")
        if reasoning:
            lines.append(f"Reasoning: {reasoning}")

        # Extra strategy fields
        entry_type = result.strategy_decision.get("entry_type")
        if entry_type:
            lines.append(f"Entry type: {entry_type}")

    # Moderation
    if result.moderation_result:
        lines.append(f"\n*Moderation:* {result.moderation_consensus}")
        # GPT-4o (Skeptic)
        gpt = result.moderation_result.get("gpt4o_verdict")
        if gpt:
            lines.append(f"  • GPT-4o (Skeptic): {_format_gpt_moderator_header(gpt)}")
            r = gpt.get("reasoning", "")
            if r:
                lines.append(f"    {r}")
        # Gemini (Risk Assessor)
        gem = result.moderation_result.get("gemini_verdict")
        if gem:
            lines.append(f"  • Gemini (Risk): {_format_gemini_moderator_header(gem)}")
            r = _format_gemini_reasoning(gem)
            if r:
                lines.append(f"    {r}")
    elif result.moderation_consensus:
        lines.append(f"\n*Moderation:* {result.moderation_consensus}")

    lines.append("\n_No order placed._")
    return "\n".join(lines)


def _format_executed_reply(result: "SingleTickerResult", ticker: str) -> str:
    """Format BUY/SELL executed response."""
    action = result.user_action
    qty = result.quantity
    price = result.price
    value = result.value_gbp
    exec_status = result.execution_result.get("status", "unknown") if result.execution_result else "unknown"

    lines = [f"*{action} {ticker}* — {exec_status}"]
    lines.append(f"Mode: {_mode_label(result)}")
    if qty and price:
        if result.price_gbp and abs(result.price_gbp - price) > 0.01:
            lines.append(
                f"Quantity: {qty:.2f} | Native price: ${price:.2f} | Target value: £{value:.2f}"
            )
        else:
            lines.append(f"Quantity: {qty:.2f} @ ${price:.2f} = £{value:.2f}")

    # Show if user overrode strategy
    if result.strategy_action and result.strategy_action != action:
        lines.append(f"(Strategy suggested {result.strategy_action}; you overrode to {action})")

    if result.strategy_decision:
        alloc = result.strategy_decision.get("target_allocation_pct", "—")
        stop = result.strategy_decision.get("stop_loss_pct", "—")
        lines.append(f"Strategy: {result.strategy_action or 'N/A'} (conviction {result.conviction})")
        lines.append(f"Allocation: {alloc}% | Stop-loss: {stop}%")
        reasoning = result.strategy_decision.get("reasoning", "")
        if reasoning:
            lines.append(f"Reasoning: {reasoning}")

    if result.moderation_overridden:
        lines.append(
            f"Moderation: *OVERRIDDEN* (force {result.user_action.lower()} — moderation BLOCKED bypassed)"
        )
    elif result.moderation_consensus:
        lines.append(f"Moderation: {result.moderation_consensus}")
    if result.moderation_result:
        gpt = result.moderation_result.get("gpt4o_verdict")
        if gpt:
            lines.append(f"  • GPT-4o (Skeptic): {_format_gpt_moderator_header(gpt)}")
            r = gpt.get("reasoning", "")
            if r:
                lines.append(f"    {r}")
        gem = result.moderation_result.get("gemini_verdict")
        if gem:
            lines.append(f"  • Gemini (Risk): {_format_gemini_moderator_header(gem)}")
            r = _format_gemini_reasoning(gem)
            if r:
                lines.append(f"    {r}")

    # Risk verdict — highlight force override
    if result.risk_verdict_str == "OVERRIDDEN":
        lines.append(f"Risk: *OVERRIDDEN* (force {result.user_action.lower()} — risk VETO bypassed)")
        triggered = (result.risk_verdict or {}).get("triggered_rules", [])
        if triggered:
            lines.append(f"Overridden rules: {', '.join(triggered)}")
    elif result.risk_verdict_str:
        lines.append(f"Risk: {result.risk_verdict_str}")
    if result.risk_verdict and result.risk_verdict.get("triggered_rules"):
        lines.append(f"Risk rules: {', '.join(result.risk_verdict['triggered_rules'])}")

    if result.execution_result:
        order_id = result.execution_result.get("order_id")
        if order_id:
            lines.append(f"Order ID: {order_id}")
    if result.result_details and result.result_details.get("force_ignored"):
        lines.append("Force prefix was recorded but not needed for direct trade mode.")

    tip = _execution_tip(result)
    if tip:
        lines.append(f"_Tip: {tip}_")

    return "\n".join(lines)


def _format_rejected_reply(result: "SingleTickerResult", ticker: str) -> str:
    """Format rejected response with full pipeline details."""
    reason = result.rejection_reason or "Unknown reason"
    lines = [f"*Rejected: {result.user_action} {ticker}*"]
    lines.append(f"Mode: {_mode_label(result)}")

    # Price
    if result.price:
        lines.append(f"Price: ${result.price:.2f}")

    lines.append(f"\n*Reason:* {reason}")

    # Strategy
    if result.strategy_decision:
        action = result.strategy_action or "HOLD"
        conv = result.conviction
        alloc = result.strategy_decision.get("target_allocation_pct", "—")
        stop = result.strategy_decision.get("stop_loss_pct", "—")
        lines.append(f"\n*Strategy:* {action} (conviction {conv})")
        lines.append(f"Allocation: {alloc}% | Stop-loss: {stop}%")
        reasoning = result.strategy_decision.get("reasoning", "")
        if reasoning:
            lines.append(f"Reasoning: {reasoning}")

    # Moderation
    if result.moderation_result:
        lines.append(f"\n*Moderation:* {result.moderation_consensus}")
        gpt = result.moderation_result.get("gpt4o_verdict")
        if gpt:
            lines.append(f"  • GPT-4o (Skeptic): {_format_gpt_moderator_header(gpt)}")
            r = gpt.get("reasoning", "")
            if r:
                lines.append(f"    {r}")
        gem = result.moderation_result.get("gemini_verdict")
        if gem:
            lines.append(f"  • Gemini (Risk): {_format_gemini_moderator_header(gem)}")
            r = _format_gemini_reasoning(gem)
            if r:
                lines.append(f"    {r}")
    elif result.moderation_consensus:
        lines.append(f"\n*Moderation:* {result.moderation_consensus}")

    # Risk details
    if result.risk_verdict:
        triggered = result.risk_verdict.get("triggered_rules", [])
        if triggered:
            lines.append(f"\n*Risk rules triggered:* {', '.join(triggered)}")

    tip = _rejection_tip(result)
    if tip:
        lines.append(f"\n_Tip: {tip}_")

    return "\n".join(lines)


def _format_partial_reply(result: "SingleTickerResult", ticker: str) -> str:
    reason = result.rejection_reason or "Partial success"
    lines = [f"*Partial: {result.user_action} {ticker or 'command'}*"]
    lines.append(f"Mode: {_mode_label(result)}")
    lines.append(f"\n*Reason:* {reason}")
    if result.result_details:
        cancelled = len(result.result_details.get("cancelled", []))
        failures = result.result_details.get("failures", [])
        lines.append(f"Cancelled: {cancelled}")
        if failures:
            lines.append("Failures:")
            for failure in failures:
                lines.append(
                    f"  • {failure.get('ticker', '?')} order {failure.get('order_id', '?')}: {failure.get('error', 'unknown error')}"
                )
    return "\n".join(lines)


def _format_cancel_reply(result: "SingleTickerResult") -> str:
    order_class = (result.cancel_order_class or "order").replace("_", " ")
    targets = ", ".join(result.target_tickers) if result.target_tickers else "requested tickers"
    details = result.result_details or {}
    cancelled = details.get("cancelled", [])
    failures = details.get("failures", [])
    matches = details.get("matches", [])

    headline = "*Cancel"
    if result.status == "partial":
        headline = "*Partial cancel"
    elif result.status == "error":
        headline = "*Cancel error"
    lines = [f"{headline}: {order_class}*"]
    lines.append(f"Mode: {_mode_label(result)}")
    lines.append(f"Targets: {targets}")
    lines.append(f"Matched pending orders: {len(matches)}")
    lines.append(f"Cancelled: {len(cancelled)}")

    if cancelled:
        lines.append("Cancelled order IDs: " + ", ".join(cancelled))
    if failures:
        lines.append("Failures:")
        for failure in failures:
            lines.append(
                f"  • {failure.get('ticker', '?')} order {failure.get('order_id', '?')}: {failure.get('error', 'unknown error')}"
            )
    if not matches and result.status == "executed":
        lines.append("No matching pending orders were found.")
    if result.error_message:
        lines.append(f"Error: {result.error_message}")
    if result.rejection_reason and result.status == "partial":
        lines.append(result.rejection_reason)
    return "\n".join(lines)


def _format_error_reply(result: "SingleTickerResult", ticker: str) -> str:
    """Format error response."""
    error = result.error_message or "Unknown error"
    reply = f"*Error processing {result.user_action} {ticker}*\n{error}"
    tip = _error_tip(result)
    if tip:
        reply += f"\n_Tip: {tip}_"
    return reply


def _format_gpt_moderator_header(verdict: dict[str, Any]) -> str:
    """Format GPT moderator header without ambiguous placeholder scores."""
    status = verdict.get("verdict", "?")
    confidence = verdict.get("score") or verdict.get("confidence_score")
    if confidence is None:
        return status
    return f"{status} (confidence {confidence}/10)"


def _format_gemini_moderator_header(verdict: dict[str, Any]) -> str:
    """Format Gemini header with explicit score labels."""
    status = verdict.get("verdict", "?")
    parts: list[str] = []
    growth = verdict.get("growth_score")
    risk = verdict.get("risk_score")
    confidence = verdict.get("score") or verdict.get("confidence_score")
    if growth is not None:
        parts.append(f"growth {growth}/10")
    if risk is not None:
        parts.append(f"risk {risk}/10")
    if confidence is not None:
        parts.append(f"confidence {confidence}/10")
    if not parts:
        return status
    return f"{status} ({', '.join(parts)})"


def _format_gemini_reasoning(verdict: dict[str, Any]) -> str:
    """Format Gemini reasoning and explain score-driven disagreements clearly."""
    reasoning = str(verdict.get("reasoning") or verdict.get("assessment") or "").strip()
    verdict_label = str(verdict.get("verdict", "")).upper()
    growth = verdict.get("growth_score")
    risk = verdict.get("risk_score")
    confidence = verdict.get("score") or verdict.get("confidence_score")

    needs_clarifier = (
        verdict_label == "DISAGREE"
        and (
            confidence is not None
            or (growth is not None and risk is not None)
        )
    )
    if not needs_clarifier:
        return reasoning

    clarifier_parts: list[str] = []
    if growth is not None and risk is not None:
        if risk > growth:
            clarifier_parts.append(
                f"risk is higher than growth ({risk}/10 vs {growth}/10)"
            )
        else:
            clarifier_parts.append(
                f"the risk/reward balance is still not strong enough ({risk}/10 risk vs {growth}/10 growth)"
            )
    if confidence is not None and confidence <= 3:
        clarifier_parts.append(f"confidence is very low at {confidence}/10")

    if not clarifier_parts:
        return reasoning

    clarifier = "Despite the positive growth signals, " + " and ".join(clarifier_parts) + ", so Gemini disagreed."
    if not reasoning:
        return clarifier
    if clarifier in reasoning:
        return reasoning
    return f"{reasoning} {clarifier}"


def _rejection_tip(result: "SingleTickerResult") -> str:
    """Return a contextual next-step tip for rejected Slack replies."""
    ticker = result.ticker_yf or result.ticker_t212
    if result.risk_verdict_str == "REJECT":
        return f"Use `force {result.user_action.lower()} <ticker>` to override risk VETO."

    reason = (result.rejection_reason or "").strip().lower()
    if "blocked by moderation consensus" in reason:
        return f"Use `force {result.user_action.lower()} <ticker>` to override moderation BLOCKED, or `REVIEW <ticker>` to inspect the committee reasoning first."

    if "minimum order size" in reason or "below the minimum order size" in reason:
        return f"Try a larger order, for example `BUY £500 {ticker}` or use `REVIEW {ticker}` first."

    if "no open position" in reason:
        return f"Use `REVIEW {ticker}` to confirm whether you currently hold shares before selling."

    if "matching order was already placed recently" in reason or "duplicate" in reason:
        return "A similar order was already submitted. Wait a few minutes before retrying."

    if "could not determine price" in reason:
        return f"Try `REVIEW {ticker}` again after market data refresh, or retry with the live market symbol if the instrument recently changed ticker."

    return ""


def _execution_tip(result: "SingleTickerResult") -> str:
    """Return contextual guidance for executed replies."""
    exec_status = str((result.execution_result or {}).get("status", "")).lower().strip()
    if exec_status == "pending":
        return "Trading 212 accepted the order but has not filled it yet. Check the dashboard or Trading 212 for status updates."
    return ""


def _error_tip(result: "SingleTickerResult") -> str:
    """Return contextual guidance for pipeline errors."""
    error = (result.error_message or "").strip().lower()
    ticker = result.ticker_yf or result.ticker_t212

    if "could not determine price" in error:
        return f"Try `REVIEW {ticker}` again after market data refresh, or retry with the live market symbol if the instrument recently changed ticker."

    if "data fetch failed" in error or "timeout" in error:
        return f"Retry `REVIEW {ticker}` in a minute to confirm market data before sending the trade again."

    return ""
