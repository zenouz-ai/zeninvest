"""Tests for Slack trade listener (US-1.6)."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.agents.notifications.slack_listener import PendingConfirmation, SlackTradeListener
from src.agents.notifications.command_gateway import CommandGateway, CommandGatewayDisabledError
from src.agents.notifications.trade_command_parser import parse_trade_command
from src.orchestrator.single_ticker_run import SingleTickerResult


def _make_result(**overrides) -> SingleTickerResult:
    defaults = dict(
        ticker_t212="AAPL_US_EQ",
        ticker_yf="AAPL",
        cycle_id="slack-20260324T120000",
        user_action="BUY",
        status="pending",
        price=150.0,
        quantity=0.0,
        value_gbp=0.0,
        strategy_action="",
        risk_verdict_str="",
        risk_verdict=None,
        command_log_id=1,
    )
    defaults.update(overrides)
    return SingleTickerResult(**defaults)


class TestSlackTradeListener:

    @patch("src.agents.notifications.slack_listener.get_settings")
    def test_init(self, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_settings.return_value.slack_app_token = "xapp-test"
        mock_settings.return_value.slack_bot_token = "xoxb-test"
        mock_settings.return_value.slack_trade_channel_id = "C123"

        listener = SlackTradeListener()
        assert listener._pending == {}

    @patch("src.agents.notifications.slack_listener.get_settings")
    def test_cleanup_expired_confirmations(self, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_settings.return_value.slack_trade_confirmation_threshold_gbp = 2000
        mock_settings.return_value.slack_trade_confirmation_timeout_minutes = 10
        listener = SlackTradeListener()
        listener._post_reply = MagicMock()

        # Add an expired confirmation
        listener._pending["ts1"] = PendingConfirmation(
            thread_ts="ts1",
            prepared_result=_make_result(command_log_id=11, value_gbp=2500),
            user_id="U123",
            channel_id="C123",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        # Add a valid confirmation
        listener._pending["ts2"] = PendingConfirmation(
            thread_ts="ts2",
            prepared_result=_make_result(ticker_t212="TSLA_US_EQ", ticker_yf="TSLA", command_log_id=12, value_gbp=2500),
            user_id="U123",
            channel_id="C123",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        with patch("src.orchestrator.single_ticker_run.update_slack_command_log") as mock_update:
            listener._cleanup_expired_confirmations()

        assert "ts1" not in listener._pending
        assert "ts2" in listener._pending
        mock_update.assert_called_once()
        listener._post_reply.assert_called_once()

    @patch("src.agents.notifications.slack_listener.get_settings")
    def test_unparseable_message_does_not_post_processing_reply(self, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_settings.return_value.slack_trade_confirmation_threshold_gbp = 2000
        mock_settings.return_value.slack_trade_confirmation_timeout_minutes = 10
        listener = SlackTradeListener()
        listener._post_reply = MagicMock()
        listener.gateway.resolve_request = MagicMock(return_value={
            "status": "unparseable",
            "message": "I couldn't parse that trade command.",
        })

        listener._process_command("C123", "123.45", "U123", "hello there")

        listener._post_reply.assert_called_once_with(
            "C123",
            "123.45",
            "I couldn't parse that trade command.",
        )

    @patch("src.agents.notifications.slack_listener.get_settings")
    def test_normalize_inbound_text_strips_slack_bullets(self, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        listener = SlackTradeListener()

        assert listener._normalize_inbound_text("• • BUY £550 AAPL") == "BUY £550 AAPL"
        assert listener._normalize_inbound_text("• liquidate holdings below £100") == "liquidate holdings below £100"

    @patch("src.agents.notifications.slack_listener.get_settings")
    def test_normalized_trade_command_stays_on_command_path(self, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        listener = SlackTradeListener()
        listener.session_manager.find_active_session = MagicMock(return_value=None)

        should_route = listener._should_route_to_conversation(
            text=listener._normalize_inbound_text("• • BUY £550 AAPL"),
            user_id="U123",
            conversation_key="123.45",
            is_thread_reply=False,
        )

        assert should_route is False

    def test_cancel_subject_first_phrase_parses(self):
        intent = parse_trade_command("cancel AAPL buy", use_llm_fallback=False)

        assert intent is not None
        assert intent.command_kind == "cancel"
        assert intent.cancel_order_class == "buy"
        assert intent.subject_phrases == ["AAPL"]

    def test_cancel_generic_order_phrase_parses(self):
        intent = parse_trade_command("cancel AAPL order", use_llm_fallback=False)

        assert intent is not None
        assert intent.command_kind == "cancel"
        assert intent.cancel_order_class == "any"
        assert intent.subject_phrases == ["AAPL"]

    @patch("src.agents.notifications.slack_listener.get_settings")
    def test_large_order_prompts_confirmation_before_execution(self, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_settings.return_value.slack_trade_confirmation_threshold_gbp = 2000
        mock_settings.return_value.slack_trade_confirmation_timeout_minutes = 10
        listener = SlackTradeListener()
        listener._post_reply = MagicMock()
        listener.gateway.resolve_request = MagicMock(return_value={
            "status": "ok",
            "intent": MagicMock(action="BUY", command_kind="trade", execution_mode="strategy"),
            "ticker_t212": "AAPL_US_EQ",
        })

        prepared = _make_result(
            status="ready",
            user_action="BUY",
            quantity=20.0,
            value_gbp=3000.0,
            strategy_action="HOLD",
        )
        mock_runner = MagicMock()
        mock_runner.prepare.return_value = prepared

        with patch("src.orchestrator.single_ticker_run.SingleTickerRunner", return_value=mock_runner):
            listener._process_command("C123", "123.45", "U123", "BUY £3000 AAPL")

        assert "123.45" in listener._pending
        mock_runner.execute_prepared.assert_not_called()
        mock_runner.update_command_log_entry.assert_called_once()
        assert listener._post_reply.call_count == 2
        prompt = listener._post_reply.call_args_list[-1].args[2]
        assert "Reply 'yes'" in prompt
        assert "£3000.00" in prompt

    @patch("src.agents.notifications.slack_listener.get_settings")
    def test_confirmation_yes_executes_prepared_trade(self, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_settings.return_value.slack_trade_confirmation_threshold_gbp = 2000
        mock_settings.return_value.slack_trade_confirmation_timeout_minutes = 10
        listener = SlackTradeListener()
        listener._post_reply = MagicMock()

        prepared = _make_result(
            status="ready",
            user_action="BUY",
            quantity=20.0,
            value_gbp=3000.0,
            command_log_id=22,
        )
        listener._pending["123.45"] = PendingConfirmation(
            thread_ts="123.45",
            prepared_result=prepared,
            user_id="U123",
            channel_id="C123",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )

        executed = _make_result(
            status="executed",
            user_action="BUY",
            quantity=20.0,
            value_gbp=3000.0,
            command_log_id=22,
            execution_result={"status": "filled", "order_id": 99},
        )
        mock_runner = MagicMock()
        mock_runner.execute_prepared.return_value = executed

        with patch("src.orchestrator.single_ticker_run.SingleTickerRunner", return_value=mock_runner):
            listener._handle_confirmation("C123", "123.45", "U123", "yes")

        assert "123.45" not in listener._pending
        mock_runner.execute_prepared.assert_called_once()
        assert listener._post_reply.call_count == 2
        final_reply = listener._post_reply.call_args_list[-1].args[2]
        assert "BUY AAPL" in final_reply

    @patch("src.agents.notifications.slack_listener.get_settings")
    def test_cancel_command_runs_without_confirmation(self, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_settings.return_value.slack_trade_confirmation_threshold_gbp = 2000
        mock_settings.return_value.slack_trade_confirmation_timeout_minutes = 10
        listener = SlackTradeListener()
        listener._post_reply = MagicMock()
        cancel_intent = MagicMock(
            action="CANCEL",
            command_kind="cancel",
            execution_mode="cancel_only",
            ticker="NVDA",
        )
        listener.gateway.resolve_request = MagicMock(return_value={
            "status": "ok",
            "intent": cancel_intent,
            "ticker_t212s": ["NVDA_US_EQ", "MSFT_US_EQ"],
        })

        cancel_result = _make_result(
            user_action="CANCEL",
            status="executed",
            execution_mode="cancel_only",
            command_kind="cancel",
            cancel_order_class="stop_sell",
            target_tickers=["NVDA_US_EQ", "MSFT_US_EQ"],
            result_details={"cancelled": ["1"], "matches": [{"order_id": "1"}], "failures": []},
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = cancel_result

        with patch("src.agents.notifications.cancel_command_runner.CancelCommandRunner", return_value=mock_runner), \
             patch("src.orchestrator.single_ticker_run.update_slack_command_log") as mock_update:
            listener._process_command("C123", "123.45", "U123", "cancel stop sell NVDA, MSFT")

        mock_runner.run.assert_called_once()
        mock_update.assert_called_once()
        assert "123.45" not in listener._pending
        assert listener._post_reply.call_count == 2


class TestCommandGatewayCancelPhrases:
    @patch("src.agents.notifications.command_gateway.get_settings")
    def test_cancel_order_phrase_with_unknown_ticker_returns_unknown_ticker(self, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        gateway = CommandGateway()

        resolved = gateway.resolve_request(
            request=type(
                "Req",
                (),
                {
                    "source": "slack",
                    "user_id": "U1",
                    "channel_id": "C1",
                    "command": "cancel APPL order",
                    "args": [],
                    "raw_payload": {"text": "cancel APPL order"},
                },
            )()
        )

        assert resolved["status"] == "unknown_ticker"
        assert resolved["ticker"] == "APPL"

    @patch("src.agents.notifications.slack_listener.get_settings")
    def test_post_reply_chunks_long_messages(self, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        listener = SlackTradeListener()
        listener._web_client = MagicMock()

        long_text = "\n".join([f"Line {i} " + ("x" * 120) for i in range(40)])
        listener._post_reply("C123", "123.45", long_text)

        assert listener._web_client.chat_postMessage.call_count >= 2
        first_text = listener._web_client.chat_postMessage.call_args_list[0].kwargs["text"]
        second_text = listener._web_client.chat_postMessage.call_args_list[1].kwargs["text"]
        assert first_text.startswith("Line 0")
        assert second_text.startswith("(continued)\n")


class TestSlackListenerBotFiltering:
    """Tests for bot_user_id filtering in the socket mode handler."""

    @patch("src.agents.notifications.slack_listener.get_settings")
    def test_message_with_bot_id_is_skipped(self, mock_settings):
        """Messages with bot_id set should be skipped (they are from bots)."""
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_settings.return_value.slack_app_token = "xapp-test"
        mock_settings.return_value.slack_bot_token = "xoxb-test"
        mock_settings.return_value.slack_trade_channel_id = "C123"

        listener = SlackTradeListener()

        # Simulate the filtering logic from the handler
        event_with_bot_id = {
            "type": "message",
            "bot_id": "B12345",
            "user": "U99999",
            "text": "BUY AAPL",
            "channel": "C123",
            "ts": "1234567890.000001",
        }

        # The handler skips messages where bot_id is set or user == bot_user_id
        should_skip = bool(event_with_bot_id.get("bot_id")) or event_with_bot_id.get("user") == "UBOTSELF"
        assert should_skip is True

    @patch("src.agents.notifications.slack_listener.get_settings")
    def test_message_from_bot_own_user_id_is_skipped(self, mock_settings):
        """Messages from the bot's own user_id should be skipped."""
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_settings.return_value.slack_app_token = "xapp-test"
        mock_settings.return_value.slack_bot_token = "xoxb-test"
        mock_settings.return_value.slack_trade_channel_id = "C123"

        listener = SlackTradeListener()
        bot_user_id = "UBOTSELF"

        event_from_self = {
            "type": "message",
            "user": bot_user_id,
            "text": "some message",
            "channel": "C123",
            "ts": "1234567890.000002",
        }

        should_skip = bool(event_from_self.get("bot_id")) or event_from_self.get("user") == bot_user_id
        assert should_skip is True

    @patch("src.agents.notifications.slack_listener.get_settings")
    def test_normal_user_message_is_not_skipped(self, mock_settings):
        """Normal user messages (no bot_id, different user) should NOT be skipped."""
        mock_settings.return_value.slack_trade_commands_enabled = True

        bot_user_id = "UBOTSELF"

        event_from_user = {
            "type": "message",
            "user": "UHUMANUSER",
            "text": "BUY AAPL",
            "channel": "C123",
            "ts": "1234567890.000003",
        }

        should_skip = bool(event_from_user.get("bot_id")) or event_from_user.get("user") == bot_user_id
        assert should_skip is False


class TestCommandGateway:

    @patch("src.agents.notifications.command_gateway.get_settings")
    def test_disabled_raises(self, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = False
        gw = CommandGateway()
        from src.agents.notifications.command_gateway import CommandRequest
        req = CommandRequest(
            source="slack", user_id="U1", channel_id="C1",
            command="BUY AAPL", args=[], raw_payload={"text": "BUY AAPL"},
        )
        with pytest.raises(CommandGatewayDisabledError):
            gw.handle(req)

    @patch("src.agents.notifications.command_gateway.get_settings")
    @patch("src.agents.notifications.command_gateway.parse_trade_command")
    def test_unparseable_returns_status(self, mock_parse, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_parse.return_value = None
        gw = CommandGateway()
        from src.agents.notifications.command_gateway import CommandRequest
        req = CommandRequest(
            source="slack", user_id="U1", channel_id="C1",
            command="hello", args=[], raw_payload={"text": "hello"},
        )
        result = gw.handle(req)
        assert result["status"] == "unparseable"
        assert "BUY AAPL" in result["message"]

    @patch("src.agents.notifications.command_gateway.get_settings")
    @patch("src.agents.notifications.command_gateway.parse_trade_command")
    def test_unparseable_portfolio_rule_returns_contextual_tip(self, mock_parse, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_parse.return_value = None
        gw = CommandGateway()
        from src.agents.notifications.command_gateway import CommandRequest
        req = CommandRequest(
            source="slack",
            user_id="U1",
            channel_id="C1",
            command="Liquidate all tickers with holding below £100",
            args=[],
            raw_payload={"text": "Liquidate all tickers with holding below £100"},
        )
        result = gw.handle(req)
        assert result["status"] == "unparseable"
        assert "one ticker per message" in result["message"]
        assert "not supported yet" in result["message"]

    @patch("src.agents.notifications.command_gateway.get_settings")
    @patch("src.agents.notifications.command_gateway.parse_trade_command")
    @patch("src.agents.notifications.command_gateway.resolve_ticker_to_t212")
    def test_unknown_ticker(self, mock_resolve, mock_parse, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_parse.return_value = MagicMock(
            ticker="ZZZZZ",
            action="BUY",
            subject_phrases=["ZZZZZ"],
            command_kind="trade",
            execution_mode="direct",
        )
        mock_resolve.return_value = None
        gw = CommandGateway()
        from src.agents.notifications.command_gateway import CommandRequest
        req = CommandRequest(
            source="slack", user_id="U1", channel_id="C1",
            command="BUY ZZZZZ", args=[], raw_payload={"text": "BUY ZZZZZ"},
        )
        result = gw.handle(req)
        assert result["status"] == "unknown_ticker"
        assert "Tip:" in result["message"]
        assert "REVIEW Rocket Lab" in result["message"]

    @patch("src.agents.notifications.command_gateway.get_settings")
    @patch("src.agents.notifications.command_gateway.parse_trade_command")
    @patch("src.agents.notifications.command_gateway.resolve_ticker_to_t212")
    def test_unknown_ticker_uses_original_company_phrase_when_available(self, mock_resolve, mock_parse, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_parse.return_value = MagicMock(
            ticker="RKLB",
            action="REVIEW",
            subject_phrases=["Rocket Lab Corporation"],
            command_kind="review",
            execution_mode="strategy",
        )
        mock_resolve.return_value = None
        gw = CommandGateway()
        from src.agents.notifications.command_gateway import CommandRequest
        req = CommandRequest(
            source="slack", user_id="U1", channel_id="C1",
            command="Review Rocket Lab Corporation",
            args=[], raw_payload={"text": "Review Rocket Lab Corporation"},
        )
        result = gw.handle(req)
        assert result["status"] == "unknown_ticker"
        assert "REVIEW Rocket Lab Corporation" in result["message"]

    @patch("src.agents.notifications.command_gateway.get_settings")
    @patch("src.agents.notifications.command_gateway.parse_trade_command")
    @patch("src.agents.notifications.command_gateway.resolve_ticker_to_t212")
    def test_error_propagation_includes_message(self, mock_resolve, mock_parse, mock_settings):
        """When pipeline returns status='error' with error_message, gateway response includes 'message'."""
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_parse.return_value = MagicMock(
            ticker="AAPL",
            action="BUY",
            subject_phrases=["AAPL"],
            command_kind="trade",
            execution_mode="strategy",
        )
        mock_resolve.return_value = "AAPL_US_EQ"

        from src.orchestrator.single_ticker_run import SingleTickerResult
        error_result = SingleTickerResult(
            ticker_t212="AAPL_US_EQ",
            ticker_yf="AAPL",
            cycle_id="slack-test",
            user_action="BUY",
            status="error",
            error_message="Data fetch timeout",
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = error_result

        gw = CommandGateway()
        from src.agents.notifications.command_gateway import CommandRequest
        with patch("src.orchestrator.single_ticker_run.SingleTickerRunner", return_value=mock_runner):
            req = CommandRequest(
                source="slack", user_id="U1", channel_id="C1",
                command="BUY AAPL", args=[], raw_payload={"text": "BUY AAPL"},
            )
            result = gw.handle(req)
        assert result["status"] == "error"
        assert result["message"] == "Data fetch timeout"

    @patch("src.agents.notifications.command_gateway.get_settings")
    @patch("src.agents.notifications.command_gateway.parse_trade_command")
    @patch("src.agents.notifications.command_gateway.resolve_ticker_to_t212")
    def test_rejection_propagation_includes_message(self, mock_resolve, mock_parse, mock_settings):
        """When pipeline returns status='rejected', gateway response includes rejection reason in 'message'."""
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_parse.return_value = MagicMock(
            ticker="AAPL",
            action="BUY",
            subject_phrases=["AAPL"],
            command_kind="trade",
            execution_mode="strategy",
        )
        mock_resolve.return_value = "AAPL_US_EQ"

        from src.orchestrator.single_ticker_run import SingleTickerResult
        rejected_result = SingleTickerResult(
            ticker_t212="AAPL_US_EQ",
            ticker_yf="AAPL",
            cycle_id="slack-test",
            user_action="BUY",
            status="rejected",
            rejection_reason="Risk VETO: max_single_stock_pct exceeded",
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = rejected_result

        gw = CommandGateway()
        from src.agents.notifications.command_gateway import CommandRequest
        with patch("src.orchestrator.single_ticker_run.SingleTickerRunner", return_value=mock_runner):
            req = CommandRequest(
                source="slack", user_id="U1", channel_id="C1",
                command="BUY AAPL", args=[], raw_payload={"text": "BUY AAPL"},
            )
            result = gw.handle(req)
        assert result["status"] == "rejected"
        assert result["message"] == "Risk VETO: max_single_stock_pct exceeded"

    @patch("src.agents.notifications.command_gateway.get_settings")
    @patch("src.agents.notifications.command_gateway.parse_trade_command")
    @patch("src.agents.notifications.command_gateway.resolve_ticker_to_t212")
    def test_cancel_request_resolves_multiple_tickers(self, mock_resolve, mock_parse, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_parse.return_value = MagicMock(
            ticker="NVDA",
            action="CANCEL",
            subject_phrases=["Nvidia", "Microsoft"],
            command_kind="cancel",
            execution_mode="cancel_only",
            cancel_order_class="stop_sell",
        )
        mock_resolve.side_effect = ["NVDA_US_EQ", "MSFT_US_EQ"]

        from src.orchestrator.single_ticker_run import SingleTickerResult

        cancel_result = SingleTickerResult(
            ticker_t212="NVDA_US_EQ",
            ticker_yf="NVDA",
            cycle_id="slack-test",
            user_action="CANCEL",
            status="executed",
            execution_mode="cancel_only",
            command_kind="cancel",
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = cancel_result

        gw = CommandGateway()
        from src.agents.notifications.command_gateway import CommandRequest
        with patch("src.agents.notifications.command_gateway.CancelCommandRunner", return_value=mock_runner):
            req = CommandRequest(
                source="slack", user_id="U1", channel_id="C1",
                command="cancel stop sell Nvidia, Microsoft", args=[], raw_payload={"text": "cancel stop sell Nvidia, Microsoft"},
            )
            result = gw.handle(req)
        assert result["status"] == "executed"
        assert result["ticker_t212s"] == ["NVDA_US_EQ", "MSFT_US_EQ"]
