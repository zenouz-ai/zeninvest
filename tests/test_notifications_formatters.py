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
    event.payload["decisions"][0]["stage_reason"] = "Awaiting 2nd cycle for promotion"

    messages = render_event(event, "slack", slack_max_chars=10_000)
    text = messages[0].body

    assert "AAPL_US_EQ BUY" in text
    assert "queued" in text
    assert "opportunity_queue" in text
    assert "Awaiting 2nd cycle for promotion" in text


def _trade_execution_event(
    *,
    stop_loss_status: str = "placed",
    stop_loss_error: str | None = None,
    error_message: str | None = None,
) -> NotificationEvent:
    return NotificationEvent(
        event_id="evt-exec-1",
        event_type="trade_execution_result",
        occurred_at=datetime.now(timezone.utc),
        cycle_id="cycle_20260310_1815",
        severity="info",
        source="orchestrator",
        dedup_key="exec-dedup-1",
        payload={
            "cycle_id": "cycle_20260310_1815",
            "dry_run": False,
            "ticker": "VRTX_US_EQ",
            "action": "BUY",
            "execution_status": "filled",
            "quantity": 1.59,
            "price": 501.47,
            "value_gbp": 797.34,
            "stop_loss_pct": -8.0,
            "stop_loss_status": stop_loss_status,
            "stop_loss_error": stop_loss_error,
            "error_message": error_message,
            "reasoning_summary": "Strong fundamentals",
            "moderation_consensus": "APPROVED",
            "risk_verdict": "APPROVE",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def test_trade_execution_email_includes_stop_loss_error_when_failed() -> None:
    """When stop-loss fails, stop_loss_error is shown in the email."""
    event = _trade_execution_event(
        stop_loss_status="failed",
        stop_loss_error="HTTP 400: Invalid timeValidity 'GTC'",
    )

    messages = render_event(event, "email")
    body = messages[0].body

    assert "Stop-loss status: failed" in body
    assert "Stop-loss error: HTTP 400: Invalid timeValidity" in body


def test_trade_execution_slack_includes_stop_loss_error_when_failed() -> None:
    """When stop-loss fails, stop_loss_error is shown in the Slack message."""
    event = _trade_execution_event(
        stop_loss_status="failed",
        stop_loss_error="HTTP 400: Invalid timeValidity 'GTC'",
    )

    messages = render_event(event, "slack")
    text = messages[0].body

    assert "Stop-loss error:" in text
    assert "Invalid timeValidity" in text


def test_trade_execution_no_error_when_stop_loss_placed() -> None:
    """When stop-loss is placed, no error line for stop-loss."""
    event = _trade_execution_event(stop_loss_status="placed")

    messages = render_event(event, "email")
    body = messages[0].body

    assert "Stop-loss status: placed" in body
    assert "Stop-loss error:" not in body


# --- Slack Trade Command Reply Formatters (US-1.6) ---

from src.agents.notifications.formatters import format_trade_command_reply
from src.orchestrator.single_ticker_run import SingleTickerResult


def _make_result(**overrides) -> SingleTickerResult:
    """Helper to create a SingleTickerResult with sensible defaults."""
    defaults = dict(
        ticker_t212="AAPL_US_EQ",
        ticker_yf="AAPL",
        cycle_id="slack-20260324T120000",
        user_action="BUY",
        status="pending",
        strategy_decision=None,
        moderation_result=None,
        risk_verdict=None,
        execution_result=None,
        rejection_reason=None,
        error_message=None,
        conviction=0,
        strategy_action="",
        moderation_consensus="",
        risk_verdict_str="",
        price=0.0,
        quantity=0.0,
        value_gbp=0.0,
    )
    defaults.update(overrides)
    return SingleTickerResult(**defaults)


class TestFormatReviewReply:

    def test_review_shows_full_reasoning_not_truncated(self):
        long_reasoning = "A" * 500
        result = _make_result(
            status="review_only",
            user_action="REVIEW",
            strategy_decision={
                "action": "BUY",
                "conviction": 75,
                "target_allocation_pct": 6.0,
                "stop_loss_pct": -8,
                "reasoning": long_reasoning,
            },
            strategy_action="BUY",
            conviction=75,
            price=150.0,
        )
        reply = format_trade_command_reply(result)
        # Full reasoning should be included, not truncated
        assert long_reasoning in reply

    def test_review_includes_per_moderator_verdicts(self):
        result = _make_result(
            status="review_only",
            user_action="REVIEW",
            strategy_decision={
                "action": "BUY",
                "conviction": 80,
                "target_allocation_pct": 5.0,
                "stop_loss_pct": -8,
                "reasoning": "Strong momentum",
            },
            strategy_action="BUY",
            conviction=80,
            price=150.0,
            moderation_consensus="APPROVED",
            moderation_result={
                "consensus": "APPROVED",
                "gpt4o_verdict": {
                    "verdict": "AGREE",
                    "score": 8,
                    "reasoning": "Valuation is justified given growth trajectory.",
                },
                "gemini_verdict": {
                    "verdict": "AGREE",
                    "score": 7,
                    "reasoning": "Risk-adjusted return is attractive.",
                },
            },
        )
        reply = format_trade_command_reply(result)
        assert "GPT-4o (Skeptic): AGREE" in reply
        assert "confidence 8/10" in reply
        assert "Valuation is justified" in reply
        assert "Gemini (Risk): AGREE" in reply
        assert "confidence 7/10" in reply
        assert "Risk-adjusted return" in reply

    def test_review_includes_price_allocation_stop_loss(self):
        result = _make_result(
            status="review_only",
            user_action="REVIEW",
            strategy_decision={
                "action": "BUY",
                "conviction": 70,
                "target_allocation_pct": 7.5,
                "stop_loss_pct": -10,
                "reasoning": "Solid fundamentals",
            },
            strategy_action="BUY",
            conviction=70,
            price=200.50,
        )
        reply = format_trade_command_reply(result)
        assert "$200.50" in reply
        assert "7.5%" in reply
        assert "-10%" in reply


class TestFormatExecutedReply:

    def test_executed_shows_execution_details(self):
        result = _make_result(
            status="executed",
            user_action="BUY",
            price=150.0,
            quantity=3.5,
            value_gbp=525.0,
            moderation_consensus="APPROVED",
            risk_verdict_str="APPROVE",
            conviction=82,
            strategy_action="BUY",
            strategy_decision={
                "action": "BUY",
                "target_allocation_pct": 5.0,
                "stop_loss_pct": -8,
                "reasoning": "Strong setup with improving fundamentals.",
            },
            execution_result={
                "status": "filled",
                "order_id": 42,
                "ticker": "AAPL_US_EQ",
            },
        )
        reply = format_trade_command_reply(result)
        assert "BUY AAPL" in reply
        assert "filled" in reply
        assert "3.50" in reply
        assert "$150.00" in reply
        assert "£525.00" in reply
        assert "Order ID: 42" in reply
        assert "Moderation: APPROVED" in reply
        assert "Risk: APPROVE" in reply
        assert "Strategy: BUY (conviction 82)" in reply
        assert "Strong setup with improving fundamentals." in reply

    def test_executed_shows_user_override(self):
        result = _make_result(
            status="executed",
            user_action="BUY",
            strategy_action="HOLD",
            price=150.0,
            quantity=3.0,
            value_gbp=450.0,
            execution_result={"status": "dry_run"},
        )
        reply = format_trade_command_reply(result)
        assert "Strategy suggested HOLD" in reply
        assert "you overrode to BUY" in reply

    def test_executed_pending_includes_status_tip(self):
        result = _make_result(
            status="executed",
            user_action="BUY",
            execution_result={"status": "pending", "order_id": 123},
        )

        reply = format_trade_command_reply(result)

        assert "BUY AAPL" in reply
        assert "pending" in reply
        assert "Trading 212 accepted the order but has not filled it yet" in reply

    def test_executed_force_sell_uses_action_specific_wording(self):
        result = _make_result(
            status="executed",
            user_action="SELL",
            risk_verdict_str="OVERRIDDEN",
            risk_verdict={"triggered_rules": ["cash_floor"]},
            execution_result={"status": "filled"},
        )
        reply = format_trade_command_reply(result)
        assert "force sell" in reply
        assert "cash_floor" in reply


class TestFormatRejectedReply:

    def test_rejected_shows_reason(self):
        result = _make_result(
            status="rejected",
            user_action="BUY",
            rejection_reason="Risk VETO: max_single_stock_pct exceeded",
            strategy_action="BUY",
            conviction=65,
            moderation_consensus="APPROVED",
            strategy_decision={
                "action": "BUY",
                "conviction": 65,
                "target_allocation_pct": 5.0,
                "stop_loss_pct": -8,
                "reasoning": "Fundamentals look solid",
            },
        )
        reply = format_trade_command_reply(result)
        assert "Rejected" in reply
        assert "Risk VETO: max_single_stock_pct exceeded" in reply
        assert "conviction 65" in reply
        assert "Moderation:* APPROVED" in reply

    def test_rejected_shows_price_and_strategy_reasoning(self):
        result = _make_result(
            status="rejected",
            user_action="BUY",
            price=415.50,
            rejection_reason="Risk VETO: Cash floor breached",
            strategy_action="BUY",
            conviction=70,
            strategy_decision={
                "action": "BUY",
                "conviction": 70,
                "target_allocation_pct": 6.0,
                "stop_loss_pct": -10,
                "reasoning": "Strong momentum with improving fundamentals",
            },
            risk_verdict={
                "verdict": "REJECT",
                "triggered_rules": ["cash_floor"],
                "reasoning": "Cash floor breached",
            },
            risk_verdict_str="REJECT",
        )
        reply = format_trade_command_reply(result)
        assert "$415.50" in reply
        assert "Strong momentum" in reply
        assert "cash_floor" in reply
        assert "force buy" in reply  # hint about force override

    def test_rejected_shows_full_strategy_reasoning_not_truncated(self):
        long_reasoning = "Microsoft has no confirmed entry signal yet. " * 30
        result = _make_result(
            status="rejected",
            user_action="BUY",
            rejection_reason="Risk VETO: cash floor",
            strategy_action="HOLD",
            conviction=58,
            strategy_decision={
                "action": "HOLD",
                "conviction": 58,
                "target_allocation_pct": 0.0,
                "stop_loss_pct": 0.0,
                "reasoning": long_reasoning,
            },
        )

        reply = format_trade_command_reply(result)

        assert long_reasoning in reply

    def test_rejected_shows_moderation_detail(self):
        result = _make_result(
            status="rejected",
            user_action="BUY",
            price=100.0,
            rejection_reason="Risk VETO: sector cap",
            strategy_action="BUY",
            conviction=75,
            strategy_decision={
                "action": "BUY",
                "conviction": 75,
                "target_allocation_pct": 5.0,
                "stop_loss_pct": -8,
                "reasoning": "Good value",
            },
            moderation_consensus="APPROVED",
            moderation_result={
                "consensus": "APPROVED",
                "gpt4o_verdict": {
                    "verdict": "AGREE",
                    "score": 8,
                    "reasoning": "Valuation looks reasonable.",
                },
                "gemini_verdict": {
                    "verdict": "AGREE",
                    "score": 7,
                    "reasoning": "Risk-reward is acceptable.",
                },
            },
            risk_verdict={
                "verdict": "REJECT",
                "triggered_rules": ["max_sector_pct"],
                "reasoning": "sector cap",
            },
            risk_verdict_str="REJECT",
        )
        reply = format_trade_command_reply(result)
        assert "GPT-4o (Skeptic): AGREE" in reply
        assert "Gemini (Risk): AGREE" in reply
        assert "max_sector_pct" in reply

    def test_rejected_hides_gpt_placeholder_score_when_missing(self):
        result = _make_result(
            status="rejected",
            user_action="BUY",
            rejection_reason="Risk VETO: sector cap",
            moderation_consensus="BLOCKED",
            moderation_result={
                "consensus": "BLOCKED",
                "gpt4o_verdict": {
                    "verdict": "DISAGREE",
                    "reasoning": "Technical confirmation is missing.",
                },
            },
        )

        reply = format_trade_command_reply(result)

        assert "GPT-4o (Skeptic): DISAGREE" in reply
        assert "score ?" not in reply

    def test_rejected_labels_gemini_scores_and_explains_disagreement(self):
        result = _make_result(
            status="rejected",
            user_action="BUY",
            rejection_reason="Risk VETO: cash floor",
            moderation_consensus="BLOCKED",
            moderation_result={
                "consensus": "BLOCKED",
                "gemini_verdict": {
                    "verdict": "DISAGREE",
                    "growth_score": 7,
                    "risk_score": 8,
                    "confidence_score": 2,
                    "assessment": "Growth potential is solid due to strong fundamentals and analyst targets.",
                },
            },
        )

        reply = format_trade_command_reply(result)

        assert "Gemini (Risk): DISAGREE (growth 7/10, risk 8/10, confidence 2/10)" in reply
        assert "risk is higher than growth (8/10 vs 7/10)" in reply
        assert "confidence is very low at 2/10" in reply

    def test_rejected_moderation_blocked_includes_contextual_tip(self):
        result = _make_result(
            status="rejected",
            user_action="BUY",
            rejection_reason="BLOCKED by moderation consensus",
            moderation_consensus="BLOCKED",
        )

        reply = format_trade_command_reply(result)

        assert "Tip:" in reply
        assert "REVIEW <ticker>" in reply
        assert "force" in reply
        assert "does not bypass moderation BLOCKED" in reply

    def test_rejected_below_minimum_order_includes_contextual_tip(self):
        result = _make_result(
            status="rejected",
            user_action="BUY",
            rejection_reason="Order value £308.68 is below the minimum order size of £500.00",
        )

        reply = format_trade_command_reply(result)

        assert "Tip:" in reply
        assert "BUY £500 AAPL" in reply
        assert "REVIEW AAPL" in reply

    def test_rejected_no_force_hint_when_not_risk_reject(self):
        """Risk-specific force override hint should not appear for unrelated rejections."""
        result = _make_result(
            status="rejected",
            user_action="SELL",
            rejection_reason="No open position in AAPL_US_EQ",
            risk_verdict_str="",
        )
        reply = format_trade_command_reply(result)
        assert "override risk VETO" not in reply

    def test_rejected_no_open_position_includes_review_tip(self):
        result = _make_result(
            status="rejected",
            user_action="SELL",
            ticker_yf="AAPL",
            rejection_reason="No open position in AAPL_US_EQ",
        )

        reply = format_trade_command_reply(result)

        assert "Tip:" in reply
        assert "REVIEW AAPL" in reply

    def test_rejected_duplicate_order_includes_wait_tip(self):
        result = _make_result(
            status="rejected",
            user_action="BUY",
            rejection_reason="A matching order was already placed recently.",
        )

        reply = format_trade_command_reply(result)

        assert "Wait a few minutes before retrying" in reply


class TestFormatForceOverrideReply:

    def test_force_override_shows_overridden_risk(self):
        result = _make_result(
            status="executed",
            user_action="BUY",
            price=415.0,
            quantity=2.0,
            value_gbp=830.0,
            moderation_consensus="APPROVED",
            risk_verdict_str="OVERRIDDEN",
            risk_verdict={
                "verdict": "REJECT",
                "triggered_rules": ["cash_floor"],
                "reasoning": "Cash floor breached",
            },
            execution_result={"status": "filled", "order_id": 99},
        )
        reply = format_trade_command_reply(result)
        assert "OVERRIDDEN" in reply
        assert "risk VETO bypassed" in reply
        assert "cash_floor" in reply
        assert "Order ID: 99" in reply


class TestFormatErrorReply:

    def test_error_shows_error_message(self):
        result = _make_result(
            status="error",
            user_action="BUY",
            error_message="Data fetch timeout for AAPL",
        )
        reply = format_trade_command_reply(result)
        assert "Error processing BUY AAPL" in reply
        assert "Data fetch timeout for AAPL" in reply
        assert "REVIEW AAPL" in reply

    def test_error_price_resolution_includes_market_data_tip(self):
        result = _make_result(
            status="error",
            user_action="BUY",
            ticker_yf="IONQ",
            error_message="Could not determine price for IONQ",
        )

        reply = format_trade_command_reply(result)

        assert "Could not determine price for IONQ" in reply
        assert "REVIEW IONQ" in reply
        assert "market symbol" in reply

    def test_error_unknown_when_no_message(self):
        result = _make_result(
            status="error",
            user_action="SELL",
        )
        reply = format_trade_command_reply(result)
        assert "Unknown error" in reply
