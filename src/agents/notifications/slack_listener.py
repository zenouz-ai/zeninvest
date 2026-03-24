"""Slack Socket Mode listener for inbound trade commands (US-1.6).

Listens for messages in a configured Slack channel, parses trade commands,
runs the single-ticker pipeline, and posts threaded replies.
"""

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    prepared_result: Any  # SingleTickerResult
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

    def _resolve_bot_user_id(self) -> str | None:
        """Get the bot's own user ID via auth.test so we can filter our own messages."""
        if not self._web_client:
            return None
        try:
            resp = self._web_client.auth_test()
            bot_id = resp.get("user_id")
            logger.info(f"Resolved bot user ID: {bot_id}")
            return bot_id
        except Exception as e:
            logger.warning(f"Could not resolve bot user ID: {e}")
            return None

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

    def start(self, shutdown_event: threading.Event | None = None) -> None:
        """Connect via Socket Mode and start listening for messages.

        Args:
            shutdown_event: Optional threading.Event that signals graceful shutdown.
                           When set, the listener closes cleanly without raising.
        """
        if not self.settings.slack_trade_commands_enabled:
            logger.warning("Slack trade commands are disabled in config. Exiting.")
            return

        self._init_slack_clients()
        channel_id = self.settings.slack_trade_channel_id

        # Resolve bot's own user ID so we never process our own messages
        bot_user_id = self._resolve_bot_user_id()

        logger.info(f"Starting Slack trade listener on channel {channel_id} (bot_user_id={bot_user_id})")

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
            # Skip our own messages (prevents cascading loop)
            if event.get("bot_id") or event.get("user") == bot_user_id:
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

        # Block main thread until shutdown signal or keyboard interrupt
        try:
            while True:
                # Use event.wait() instead of time.sleep() for clean shutdown
                if shutdown_event and shutdown_event.wait(timeout=1):
                    break
                elif not shutdown_event:
                    time.sleep(1)
                self._cleanup_expired_confirmations()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            logger.info("Slack listener shutting down gracefully...")
            try:
                self._socket_client.close()
            except Exception:
                pass
            logger.info("Slack listener stopped.")

    def _process_command(
        self, channel: str, ts: str, user_id: str, text: str
    ) -> None:
        """Process a trade command message. Runs in background thread."""
        try:
            request = CommandRequest(
                source="slack",
                user_id=user_id,
                channel_id=channel,
                command=text,
                args=[],
                raw_payload={"text": text, "ts": ts, "thread_ts": ts},
            )

            resolved = self.gateway.resolve_request(request)
            status = resolved.get("status", "error")
            ticker_t212 = resolved.get("ticker_t212", "N/A")

            if status == "unparseable":
                return

            if status == "unknown_ticker":
                self._post_reply(channel, ts, resolved.get("message", "Unknown ticker."))
                logger.info(f"Command completed: {text!r} → unknown_ticker")
                return

            self._post_reply(channel, ts, "Processing your request...")

            from src.orchestrator.single_ticker_run import SingleTickerRunner

            runner = SingleTickerRunner(dry_run=False)
            try:
                prepared_result = runner.prepare(
                    ticker_t212=ticker_t212,
                    intent=resolved["intent"],
                    user_id=user_id,
                    channel_id=channel,
                    thread_ts=ts,
                )

                if self._requires_confirmation(prepared_result):
                    expires_at = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(
                        minutes=self.settings.slack_trade_confirmation_timeout_minutes
                    )
                    prompt = self._format_confirmation_prompt(prepared_result)
                    self._pending[ts] = PendingConfirmation(
                        thread_ts=ts,
                        prepared_result=prepared_result,
                        user_id=user_id,
                        channel_id=channel,
                        expires_at=expires_at,
                    )
                    runner.update_command_log_entry(
                        prepared_result.command_log_id,
                        status="awaiting_confirmation",
                        response_message=prompt,
                    )
                    self._post_reply(channel, ts, prompt)
                    logger.info(f"Command completed: {text!r} → awaiting_confirmation ({ticker_t212})")
                    return

                final_result = prepared_result
                if prepared_result.status == "ready":
                    final_result = runner.execute_prepared(prepared_result)

                reply = format_trade_command_reply(final_result)
                runner.update_command_log_entry(
                    final_result.command_log_id,
                    response_message=reply,
                )
                self._post_reply(channel, ts, reply)
                logger.info(f"Command completed: {text!r} → {final_result.status} ({ticker_t212})")
            finally:
                runner.close()

        except CommandGatewayDisabledError:
            self._post_reply(channel, ts, "Trade commands are currently disabled.")
            logger.info(f"Command completed: {text!r} → gateway_disabled")
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
            from src.orchestrator.single_ticker_run import SingleTickerRunner

            runner = SingleTickerRunner(dry_run=False)
            try:
                runner.update_command_log_entry(
                    pending.prepared_result.command_log_id,
                    status="expired",
                    rejection_reason="Confirmation expired.",
                    response_message="Confirmation expired.",
                )
            finally:
                runner.close()
            self._post_reply(channel, thread_ts, "Confirmation expired.")
            return

        lower = message.strip().lower()
        if lower in ("yes", "y", "confirm"):
            del self._pending[thread_ts]
            self._post_reply(channel, thread_ts, "Confirmed. Executing...")

            from src.orchestrator.single_ticker_run import SingleTickerRunner

            runner = SingleTickerRunner(dry_run=False)
            try:
                final_result = runner.execute_prepared(pending.prepared_result)
                reply = format_trade_command_reply(final_result)
                runner.update_command_log_entry(
                    final_result.command_log_id,
                    response_message=reply,
                )
            finally:
                runner.close()
            self._post_reply(channel, thread_ts, reply)

        elif lower in ("no", "n", "cancel"):
            del self._pending[thread_ts]
            from src.orchestrator.single_ticker_run import SingleTickerRunner

            runner = SingleTickerRunner(dry_run=False)
            try:
                runner.update_command_log_entry(
                    pending.prepared_result.command_log_id,
                    status="cancelled",
                    rejection_reason="Cancelled by user",
                    response_message="Order cancelled.",
                )
            finally:
                runner.close()
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
        if not expired:
            return

        from src.orchestrator.single_ticker_run import SingleTickerRunner

        runner = SingleTickerRunner(dry_run=False)
        try:
            for k in expired:
                pending = self._pending.pop(k)
                runner.update_command_log_entry(
                    pending.prepared_result.command_log_id,
                    status="expired",
                    rejection_reason="Confirmation expired.",
                    response_message="Confirmation expired.",
                )
                self._post_reply(pending.channel_id, pending.thread_ts, "Confirmation expired.")
        finally:
            runner.close()

    def _requires_confirmation(self, result: Any) -> bool:
        """Return True when a prepared trade exceeds the confirmation threshold."""
        return (
            result.status == "ready"
            and result.user_action in {"BUY", "SELL"}
            and result.value_gbp >= self.settings.slack_trade_confirmation_threshold_gbp
        )

    def _format_confirmation_prompt(self, result: Any) -> str:
        """Build the confirmation prompt for a prepared large order."""
        ticker = result.ticker_yf or result.ticker_t212
        timeout_minutes = self.settings.slack_trade_confirmation_timeout_minutes
        lines = [
            f"Confirm {result.user_action} {ticker}: estimated value £{result.value_gbp:.2f}",
        ]
        if result.quantity and result.price:
            lines[0] += f" ({result.quantity:.2f} @ ${result.price:.2f})"
        if result.strategy_action and result.strategy_action != result.user_action:
            lines.append(
                f"Strategy suggested {result.strategy_action}; you overrode to {result.user_action}."
            )
        if result.risk_verdict_str == "OVERRIDDEN":
            lines.append(f"Risk: OVERRIDDEN via force {result.user_action.lower()}.")
            triggered = (result.risk_verdict or {}).get("triggered_rules", [])
            if triggered:
                lines.append(f"Overridden rules: {', '.join(triggered)}")
        lines.append(
            f"Reply 'yes' in this thread within {timeout_minutes} minutes to execute, or 'no' to cancel."
        )
        return "\n".join(lines)
