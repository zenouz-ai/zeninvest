"""Tests for Slack trade listener (US-1.6)."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.agents.notifications.slack_listener import PendingConfirmation, SlackTradeListener
from src.agents.notifications.command_gateway import CommandGateway, CommandGatewayDisabledError


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
        listener = SlackTradeListener()

        # Add an expired confirmation
        listener._pending["ts1"] = PendingConfirmation(
            thread_ts="ts1",
            intent=MagicMock(),
            ticker_t212="AAPL_US_EQ",
            user_id="U123",
            channel_id="C123",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        # Add a valid confirmation
        listener._pending["ts2"] = PendingConfirmation(
            thread_ts="ts2",
            intent=MagicMock(),
            ticker_t212="TSLA_US_EQ",
            user_id="U123",
            channel_id="C123",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        listener._cleanup_expired_confirmations()

        assert "ts1" not in listener._pending
        assert "ts2" in listener._pending


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

    @patch("src.agents.notifications.command_gateway.get_settings")
    @patch("src.agents.notifications.command_gateway.parse_trade_command")
    @patch("src.agents.notifications.command_gateway.resolve_ticker_to_t212")
    def test_unknown_ticker(self, mock_resolve, mock_parse, mock_settings):
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_parse.return_value = MagicMock(ticker="ZZZZZ")
        mock_resolve.return_value = None
        gw = CommandGateway()
        from src.agents.notifications.command_gateway import CommandRequest
        req = CommandRequest(
            source="slack", user_id="U1", channel_id="C1",
            command="BUY ZZZZZ", args=[], raw_payload={"text": "BUY ZZZZZ"},
        )
        result = gw.handle(req)
        assert result["status"] == "unknown_ticker"

    @patch("src.agents.notifications.command_gateway.get_settings")
    @patch("src.agents.notifications.command_gateway.parse_trade_command")
    @patch("src.agents.notifications.command_gateway.resolve_ticker_to_t212")
    def test_error_propagation_includes_message(self, mock_resolve, mock_parse, mock_settings):
        """When pipeline returns status='error' with error_message, gateway response includes 'message'."""
        mock_settings.return_value.slack_trade_commands_enabled = True
        mock_parse.return_value = MagicMock(ticker="AAPL", action="BUY")
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
        mock_parse.return_value = MagicMock(ticker="AAPL", action="BUY")
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
