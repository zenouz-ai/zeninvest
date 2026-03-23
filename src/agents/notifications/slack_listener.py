"""Slack Socket Mode listener for inbound trade commands (US-1.6).

Listens for messages in a configured Slack channel, parses trade commands,
runs the single-ticker pipeline, and posts threaded replies.
"""

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.agents.notifications.command_gateway import (
    CommandGateway,
    CommandGatewayDisabledError,
    CommandRequest,
)
from src.agents.notifications.formatters import format_trade_command_reply
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("slack_listener")


@dataclass
class PendingConfirmation:
    """Tracks a pending large-order confirmation."""

    thread_ts: str
    intent: Any  # TradeCommandIntent
    ticker_t212: str
    user_id: str
    channel_id: str
    expires_at: datetime


class SlackTradeListener:
    """Slack Socket Mode listener for trade commands."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.gateway = CommandGateway()
        self._pending: dict[str, PendingConfirmation] = {}

        # Lazy imports — slack-sdk may not be installed in all environments
        self._web_client = None
        self._socket_client = None

    def _init_slack_clients(self) -> None:
        """Initialize Slack clients (requires slack-sdk)."""
        from slack_sdk import WebClient
        from slack_sdk.socket_mode import SocketModeClient

        app_token = self.settings.slack_app_token
        bot_token = self.settings.slack_bot_token

        if not app_token:
            raise EnvironmentError("SLACK_APP_TOKEN is required for Socket Mode")
        if not bot_token:
            raise EnvironmentError("SLACK_BOT_TOKEN is required for WebClient")

        self._web_client = WebClient(token=bot_token)
        self._socket_client = SocketModeClient(
            app_token=app_token,
            web_client=self._web_client,
        )

    def start(self) -> None:
        """Connect via Socket Mode and start listening for messages."""
        if not self.settings.slack_trade_commands_enabled:
            logger.warning("Slack trade commands are disabled in config. Exiting.")
            return

        self._init_slack_clients()
        channel_id = self.settings.slack_trade_channel_id

        logger.info(f"Starting Slack trade listener on channel {channel_id}")

        from slack_sdk.socket_mode.request import SocketModeRequest
        from slack_sdk.socket_mode.response import SocketModeResponse

        def handler(client: Any, req: SocketModeRequest) -> None:
            # Acknowledge immediately (Slack 3-second timeout)
            client.send_socket_mode_response(
                SocketModeResponse(envelope_id=req.envelope_id)
            )

            if req.type != "events_api":
                return

            event = req.payload.get("event", {})
            if event.get("type") != "message":
                return
            # Skip bot messages, message_changed, etc.
            if event.get("subtype"):
                return
            # Filter to configured channel
            if channel_id and event.get("channel") != channel_id:
                return

            text = event.get("text", "").strip()
            user_id = event.get("user", "")
            msg_channel = event.get("channel", "")
            ts = event.get("ts", "")

            if not text:
                return

            # Check for confirmation reply in thread
            thread_ts = event.get("thread_ts")
            if thread_ts and thread_ts in self._pending:
                threading.Thread(
                    target=self._handle_confirmation,
                    args=(msg_channel, thread_ts, user_id, text),
                    daemon=True,
                    name=f"SlackConfirm-{ts}",
                ).start()
                return

            # Process as new command in background thread
            threading.Thread(
                target=self._process_command,
                args=(msg_channel, ts, user_id, text),
                daemon=True,
                name=f"SlackCmd-{ts}",
            ).start()

        self._socket_client.socket_mode_request_listeners.append(handler)

        logger.info("Slack Socket Mode connected. Listening for trade commands...")
        self._socket_client.connect()

        # Block main thread
        try:
            while True:
                time.sleep(1)
                self._cleanup_expired_confirmations()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Slack listener shutting down")
            self._socket_client.close()

    def _process_command(
        self, channel: str, ts: str, user_id: str, text: str
    ) -> None:
        """Process a trade command message. Runs in background thread."""
        try:
            # Post processing indicator
            self._post_reply(channel, ts, "Processing your request...")

            request = CommandRequest(
                source="slack",
                user_id=user_id,
                channel_id=channel,
                command=text,
                args=[],
                raw_payload={"text": text, "ts": ts, "thread_ts": ts},
            )

            result = self.gateway.handle(request)
            status = result.get("status", "error")

            if status == "unparseable":
                # Silently ignore non-trade messages (delete processing indicator)
                return

            if status == "unknown_ticker":
                self._post_reply(channel, ts, result.get("message", "Unknown ticker."))
                return

            if status == "error":
                self._post_reply(channel, ts, f"Error: {result.get('message', 'Unknown error')}")
                return

            # Format and post result
            pipeline_result = result.get("result")
            if pipeline_result:
                reply = format_trade_command_reply(pipeline_result)
                self._post_reply(channel, ts, reply)
            else:
                self._post_reply(channel, ts, f"Command completed with status: {status}")

        except CommandGatewayDisabledError:
            self._post_reply(channel, ts, "Trade commands are currently disabled.")
        except Exception as e:
            logger.error(f"Error processing command: {e}", exc_info=True)
            self._post_reply(channel, ts, f"Error: {e}")

    def _handle_confirmation(
        self, channel: str, thread_ts: str, user_id: str, message: str
    ) -> None:
        """Handle 'yes'/'no' confirmation for large orders."""
        pending = self._pending.get(thread_ts)
        if not pending:
            return

        now = datetime.now(timezone.utc)
        if now > pending.expires_at:
            del self._pending[thread_ts]
            self._post_reply(channel, thread_ts, "Confirmation expired.")
            return

        lower = message.strip().lower()
        if lower in ("yes", "y", "confirm"):
            del self._pending[thread_ts]
            self._post_reply(channel, thread_ts, "Confirmed. Executing...")

            # Run the pipeline
            request = CommandRequest(
                source="slack",
                user_id=user_id,
                channel_id=channel,
                command=pending.intent.raw_message,
                args=[],
                raw_payload={
                    "text": pending.intent.raw_message,
                    "ts": thread_ts,
                    "thread_ts": thread_ts,
                },
            )
            result = self.gateway.handle(request)
            pipeline_result = result.get("result")
            if pipeline_result:
                reply = format_trade_command_reply(pipeline_result)
                self._post_reply(channel, thread_ts, reply)

        elif lower in ("no", "n", "cancel"):
            del self._pending[thread_ts]
            self._post_reply(channel, thread_ts, "Order cancelled.")

    def _post_reply(self, channel: str, thread_ts: str, text: str) -> None:
        """Post a threaded reply via WebClient."""
        if not self._web_client:
            logger.warning("WebClient not initialized, cannot post reply")
            return
        try:
            self._web_client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=text,
            )
        except Exception as e:
            logger.error(f"Failed to post Slack reply: {e}")

    def _cleanup_expired_confirmations(self) -> None:
        """Remove expired pending confirmations."""
        now = datetime.now(timezone.utc)
        expired = [k for k, v in self._pending.items() if now > v.expires_at]
        for k in expired:
            del self._pending[k]
