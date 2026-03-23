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
