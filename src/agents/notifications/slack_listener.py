"""Slack Socket Mode listener for inbound trade commands (US-1.6).

Listens for messages in a configured Slack channel, parses Slack review/trade/
cancel commands, dispatches them to the correct runner, and posts threaded
replies.
"""

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.agents.conversation.orchestrator import ConversationOrchestrator
from src.agents.conversation.session_manager import SessionManager
from src.agents.notifications.command_gateway import (
    CommandGateway,
    CommandGatewayDisabledError,
    CommandRequest,
)
from src.agents.notifications.formatters import format_trade_command_reply
from src.agents.notifications.trade_command_parser import parse_trade_command
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("slack_listener")
SLACK_REPLY_MAX_CHARS = 3500
_LEADING_SLACK_FORMATTING_RE = re.compile(
    r"^(?:(?:>\s*)+|(?:(?:[-*•·]\s*)+)|(?:(?:\d+[\.\)]\s*)+))+",
    re.IGNORECASE,
)


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
        self.session_manager = SessionManager()
        self.conversation = ConversationOrchestrator(session_manager=self.session_manager)
        self._pending: dict[str, PendingConfirmation] = {}
        worker_count = max(1, int(getattr(self.settings, "slack_trade_worker_count", 1)))
        self._executor = ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="SlackTradeWorker",
        )

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

            raw_text = event.get("text", "")
            text = self._normalize_inbound_text(raw_text)
            user_id = event.get("user", "")
            msg_channel = event.get("channel", "")
            ts = event.get("ts", "")

            if not text:
                return

            # Check for confirmation reply in thread
            thread_ts = event.get("thread_ts")
            if thread_ts and thread_ts in self._pending:
                self._submit_task(
                    self._handle_confirmation,
                    msg_channel,
                    thread_ts,
                    user_id,
                    text,
                )
                return

            conversation_key = thread_ts or ts
            if self._should_route_to_conversation(
                text=text,
                user_id=user_id,
                conversation_key=conversation_key,
                is_thread_reply=bool(thread_ts),
            ):
                self._submit_task(
                    self._process_conversation,
                    msg_channel,
                    conversation_key,
                    user_id,
                    text,
                    raw_text,
                )
                return

            # Process as new command via a bounded worker pool so bursts do not
            # create unbounded daemon threads on a small VPS.
            self._submit_task(
                self._process_command,
                msg_channel,
                ts,
                user_id,
                text,
                raw_text,
            )

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
            except Exception:  # nosec B110
                pass
            self._executor.shutdown(wait=False, cancel_futures=False)
            logger.info("Slack listener stopped.")

    def _submit_task(self, fn: Any, *args: Any) -> None:
        """Submit a Slack command task to the bounded worker pool."""
        try:
            self._executor.submit(fn, *args)
        except RuntimeError as e:
            logger.warning(f"Slack worker pool rejected task: {e}")

    def _normalize_inbound_text(self, text: str) -> str:
        """Normalize Slack formatting so commands parse consistently."""
        normalized_lines: list[str] = []
        for raw_line in (text or "").splitlines():
            line = " ".join(raw_line.strip().split())
            while line:
                updated = _LEADING_SLACK_FORMATTING_RE.sub("", line).strip()
                if updated == line:
                    break
                line = updated
            if line:
                normalized_lines.append(line)
        return " ".join(normalized_lines).strip()

    def _should_route_to_conversation(
        self,
        *,
        text: str,
        user_id: str,
        conversation_key: str,
        is_thread_reply: bool,
    ) -> bool:
        """Decide whether an inbound Slack message belongs to the chat workflow."""
        if is_thread_reply:
            return True

        existing = self.session_manager.find_active_session(
            channel_type="slack",
            channel_session_key=conversation_key,
            user_id=user_id,
        )
        if existing is not None:
            return True

        return parse_trade_command(text, use_llm_fallback=False) is None

    def _process_conversation(
        self,
        channel: str,
        thread_ts: str,
        user_id: str,
        text: str,
        raw_text: str | None = None,
    ) -> None:
        """Process a Slack message through the shared conversational workflow."""
        try:
            session = self.conversation.start_session(
                channel_type="slack",
                user_id=user_id,
                channel_session_key=thread_ts,
                title=text[:120],
            )
            session_detail = self.conversation.process_turn(
                session_id=int(session["id"]),
                message_text=text,
                raw_message_text=raw_text,
                channel_type="slack",
                user_id=user_id,
            )
            reply = self._extract_latest_assistant_message(session_detail)
            if reply:
                self._post_reply(channel, thread_ts, reply)
            logger.info("Conversation turn completed in Slack thread %s", thread_ts)
        except Exception as e:
            logger.error("Error processing conversational Slack request: %s", e, exc_info=True)
            self._post_reply(channel, thread_ts, f"Error: {e}")

    def _process_command(
        self,
        channel: str,
        ts: str,
        user_id: str,
        text: str,
        raw_text: str | None = None,
    ) -> None:
        """Process a trade command message. Runs in background thread."""
        try:
            request = CommandRequest(
                source="slack",
                user_id=user_id,
                channel_id=channel,
                command=text,
                args=[],
                raw_payload={"text": text, "raw_text": raw_text or text, "ts": ts, "thread_ts": ts},
            )

            resolved = self.gateway.resolve_request(request)
            status = resolved.get("status", "error")
            ticker_t212 = resolved.get("ticker_t212", "N/A")
            ticker_t212s = resolved.get("ticker_t212s", [])
            requested_ticker = getattr(resolved.get("intent"), "ticker", None)
            intent = resolved.get("intent")
            if intent is not None and raw_text:
                intent.raw_message = raw_text
            command_kind = str(getattr(intent, "command_kind", "trade") or "trade").lower()
            execution_mode = str(getattr(intent, "execution_mode", "strategy") or "strategy").lower()

            if status == "unparseable":
                self._post_reply(
                    channel,
                    ts,
                    resolved.get("message", "I couldn't parse that trade command."),
                )
                logger.info(f"Command completed: {text!r} → unparseable")
                return

            if status == "unknown_ticker":
                self._post_reply(channel, ts, resolved.get("message", "Unknown ticker."))
                logger.info(f"Command completed: {text!r} → unknown_ticker")
                return

            self._post_reply(channel, ts, "Processing your request...")

            if command_kind == "cancel":
                from src.agents.notifications.cancel_command_runner import CancelCommandRunner

                runner = CancelCommandRunner(dry_run=False)
            elif execution_mode == "strategy":
                from src.orchestrator.single_ticker_run import SingleTickerRunner

                runner = SingleTickerRunner(dry_run=False)
            else:
                from src.orchestrator.direct_trade_run import DirectTradeRunner

                runner = DirectTradeRunner(dry_run=False)
            try:
                if command_kind == "cancel":
                    final_result = runner.run(
                        ticker_t212s=ticker_t212s,
                        intent=intent,
                        user_id=user_id,
                        channel_id=channel,
                        thread_ts=ts,
                    )
                    reply = format_trade_command_reply(final_result)
                    from src.orchestrator.single_ticker_run import update_slack_command_log

                    update_slack_command_log(
                        final_result.command_log_id,
                        response_message=reply,
                    )
                    self._post_reply(channel, ts, reply)
                    logger.info(
                        "Command completed: %r → %s (%s)",
                        text,
                        final_result.status,
                        ", ".join(ticker_t212s) or "cancel",
                    )
                    return

                prepared_result = runner.prepare(
                    ticker_t212=ticker_t212,
                    intent=intent,
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
                if requested_ticker and requested_ticker.upper() != ticker_t212.upper():
                    logger.info(
                        f"Command completed: {text!r} → {final_result.status} "
                        f"({requested_ticker.upper()} -> {ticker_t212})"
                    )
                else:
                    logger.info(f"Command completed: {text!r} → {final_result.status} ({ticker_t212})")
            finally:
                runner.close()

        except CommandGatewayDisabledError:
            self._post_reply(channel, ts, "Trade commands are currently disabled.")
            logger.info(f"Command completed: {text!r} → gateway_disabled")
        except Exception as e:
            logger.error(f"Error processing command: {e}", exc_info=True)
            self._post_reply(channel, ts, f"Error: {e}")

    def _extract_latest_assistant_message(self, session_detail: dict[str, Any]) -> str | None:
        """Return the latest assistant turn text from a session payload."""
        turns = list(session_detail.get("turns") or [])
        for turn in reversed(turns):
            if turn.get("role") == "assistant" and turn.get("message_text"):
                return str(turn["message_text"])
        return None

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
            from src.orchestrator.single_ticker_run import update_slack_command_log

            update_slack_command_log(
                pending.prepared_result.command_log_id,
                status="expired",
                rejection_reason="Confirmation expired.",
                response_message="Confirmation expired.",
            )
            self._post_reply(channel, thread_ts, "Confirmation expired.")
            return

        lower = message.strip().lower()
        if lower in ("yes", "y", "confirm"):
            del self._pending[thread_ts]
            self._post_reply(channel, thread_ts, "Confirmed. Executing...")

            if pending.prepared_result.execution_mode == "strategy":
                from src.orchestrator.single_ticker_run import SingleTickerRunner

                runner = SingleTickerRunner(dry_run=False)
            else:
                from src.orchestrator.direct_trade_run import DirectTradeRunner

                runner = DirectTradeRunner(dry_run=False)
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
            from src.orchestrator.single_ticker_run import update_slack_command_log

            update_slack_command_log(
                pending.prepared_result.command_log_id,
                status="cancelled",
                rejection_reason="Cancelled by user",
                response_message="Order cancelled.",
            )
            self._post_reply(channel, thread_ts, "Order cancelled.")

    def _post_reply(self, channel: str, thread_ts: str, text: str) -> None:
        """Post a threaded reply via WebClient."""
        if not self._web_client:
            logger.warning("WebClient not initialized, cannot post reply")
            return
        try:
            for idx, chunk in enumerate(self._chunk_reply(text)):
                chunk_text = chunk if idx == 0 else f"(continued)\n{chunk}"
                self._web_client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=chunk_text,
                )
        except Exception as e:
            logger.error(f"Failed to post Slack reply: {e}")

    def _chunk_reply(self, text: str, *, max_chars: int = SLACK_REPLY_MAX_CHARS) -> list[str]:
        """Split long Slack replies on line boundaries to preserve full context."""
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

    def _cleanup_expired_confirmations(self) -> None:
        """Remove expired pending confirmations."""
        now = datetime.now(timezone.utc)
        expired = [k for k, v in self._pending.items() if now > v.expires_at]
        if not expired:
            return

        from src.orchestrator.single_ticker_run import update_slack_command_log

        for k in expired:
            pending = self._pending.pop(k)
            update_slack_command_log(
                pending.prepared_result.command_log_id,
                status="expired",
                rejection_reason="Confirmation expired.",
                response_message="Confirmation expired.",
            )
            self._post_reply(pending.channel_id, pending.thread_ts, "Confirmation expired.")

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
        if result.moderation_overridden:
            lines.append(f"Moderation: OVERRIDDEN via force {result.user_action.lower()}.")
        if result.risk_verdict_str == "OVERRIDDEN":
            lines.append(f"Risk: OVERRIDDEN via force {result.user_action.lower()}.")
            triggered = (result.risk_verdict or {}).get("triggered_rules", [])
            if triggered:
                lines.append(f"Overridden rules: {', '.join(triggered)}")
        lines.append(
            f"Reply 'yes' in this thread within {timeout_minutes} minutes to execute, or 'no' to cancel."
        )
        return "\n".join(lines)
