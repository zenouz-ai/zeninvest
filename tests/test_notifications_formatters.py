from datetime import datetime, timezone

from src.agents.notifications.formatters import render_event
from src.agents.notifications.types import NotificationEvent


def _cycle_event() -> NotificationEvent:
    return NotificationEvent(
        event_id="evt-1",
        event_type="cycle_run_summary",
        occurred_at=datetime.now(timezone.utc),
        cycle_id="cycle_x",
        severity="info",
        source="orchestrator",
        dedup_key="dedup-1",
        payload={
            "cycle_id": "cycle_x",
            "status": "completed",
            "dry_run": True,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "counts": {
                "decisions": 2,
                "trades": 1,
                "rejected": 1,
                "queued": 0,
                "filtered": 0,
            },
            "decisions": [
                {
                    "ticker": "AAPL_US_EQ",
                    "action": "BUY",
                    "stage": "approved",
                    "conviction": 81,
                    "target_allocation_pct": 8,
                    "final_allocation_pct": 8,
                    "moderation_consensus": "APPROVED",
                    "risk_verdict": "APPROVE",
                    "industry": "Consumer Electronics",
                    "market_cap": 2_800_000_000_000,
                    "description_excerpt": "Apple designs smartphones and related services.",
                    "trailing_pe": 28.2,
                    "pb_ratio": 38.1,
                    "roe": 0.61,
                    "profit_margin": 0.24,
                    "debt_equity": 1.5,
                    "earnings_growth": 0.12,
                    "news_excerpt": "Positive sentiment on AI device cycle.",
                    "strategy_reasoning_excerpt": "Momentum and earnings quality remain strong.",
                    "gpt_reasoning_excerpt": "Valuation is elevated but acceptable with growth.",
                    "gemini_assessment_excerpt": "Risk manageable in current regime.",
                    "gemini_growth_score": 7,
                    "gemini_risk_score": 4,
                    "gemini_confidence_score": 7,
                    "execution_status": "filled",
                    "quantity": 12.3,
                    "value_gbp": 800,
                    "stop_loss_pct": -8.0,
                    "stop_loss_status": "placed",
                },
                {
                    "ticker": "TSLA_US_EQ",
                    "action": "HOLD",
                    "stage": "strategy_hold",
                    "conviction": 0,
                    "target_allocation_pct": 0,
                    "final_allocation_pct": 0,
                    "moderation_consensus": None,
                    "risk_verdict": None,
                    "industry": "Auto",
                    "market_cap": 700_000_000_000,
                    "description_excerpt": "EV manufacturer.",
                    "trailing_pe": None,
                    "pb_ratio": None,
                    "roe": None,
                    "profit_margin": None,
                    "debt_equity": None,
                    "earnings_growth": None,
                    "news_excerpt": "Mixed sentiment.",
                    "strategy_reasoning_excerpt": "No edge today.",
                    "gpt_reasoning_excerpt": "",
                    "gemini_assessment_excerpt": "",
                    "gemini_growth_score": None,
                    "gemini_risk_score": None,
                    "gemini_confidence_score": None,
                    "execution_status": None,
                    "quantity": None,
                    "value_gbp": None,
                    "stop_loss_pct": 0,
                    "stop_loss_status": None,
                },
            ],
        },
    )


def test_render_cycle_summary_slack_contains_rows() -> None:
    messages = render_event(_cycle_event(), "slack", slack_max_chars=10_000)

    assert len(messages) == 1
    text = messages[0].body
    assert "ℹ️ INFO" in text
    assert "[CYCLE-SUMMARY]" in text
    assert "AAPL_US_EQ BUY" in text
    assert "TSLA_US_EQ HOLD" not in text
    assert "trimmed 1 HOLD rows" in text


def test_render_cycle_summary_slack_chunking() -> None:
    event = _cycle_event()
    event.payload["decisions"] = event.payload["decisions"] * 30

    messages = render_event(event, "slack", slack_max_chars=450)
    assert len(messages) > 1
    assert all(message.body for message in messages)


def test_render_cycle_summary_email_includes_detailed_sections() -> None:
    messages = render_event(_cycle_event(), "email")

    assert len(messages) == 1
    body = messages[0].body
    assert "Ticker Decision Details" in body
    assert "Strategy reasoning" in body
    assert "Gemini scores" in body
    assert "Execution: status=filled" in body


def test_render_cycle_summary_email_uses_readable_non_execution_labels() -> None:
    event = _cycle_event()
    event.payload["decisions"][0]["execution_status"] = None
    event.payload["decisions"][0]["stop_loss_status"] = None

    messages = render_event(event, "email")
    body = messages[0].body

    assert "Execution: status=not_executed" in body
    assert "status=not_applicable" in body


def test_render_cycle_summary_slack_includes_queued_reason() -> None:
    event = _cycle_event()
    event.payload["decisions"][0]["stage"] = "opportunity_queue"
    event.payload["decisions"][0]["quantity"] = None
    event.payload["decisions"][0]["stage_reason"] = "Queued by UOV optimizer (capacity/threshold gating)"

    messages = render_event(event, "slack", slack_max_chars=10_000)
    text = messages[0].body

    assert "AAPL_US_EQ BUY" in text
    assert "queued" in text
    assert "opportunity_queue" in text
    assert "Queued by UOV optimizer (capacity/threshold gating)" in text
