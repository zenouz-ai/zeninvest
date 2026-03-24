"""Minimal session lifecycle manager for conversational trading (US-1.9 skeleton).

Provides real DB CRUD operations for chat sessions and turns.
No LLM logic, no execution — just plumbing for future conversational workflow.
"""

from datetime import datetime, timezone
from typing import Any

from src.data.database import get_session
from src.data.models import ChatSession, ChatTurn
from src.utils.logger import get_logger

logger = get_logger("session_manager")


class ChatSessionNotFoundError(LookupError):
    """Raised when a requested chat session does not exist."""


class SessionManager:
    """Manages conversational trading session lifecycle."""

    def create_session(
        self,
        channel_type: str,
        user_id: str | None = None,
        channel_session_key: str | None = None,
    ) -> int:
        """Create a new chat session.

        Args:
            channel_type: 'slack' or 'dashboard'
            user_id: Optional user identifier
            channel_session_key: Slack thread_ts or dashboard session key

        Returns:
            session_id
        """
        session = get_session()
        try:
            chat_session = ChatSession(
                status="active",
                channel_type=channel_type,
                channel_session_key=channel_session_key,
                user_id=user_id,
            )
            session.add(chat_session)
            session.commit()
            session_id = chat_session.id
            logger.info(f"Created chat session {session_id} ({channel_type})")
            return session_id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def add_turn(
        self,
        session_id: int,
        role: str,
        message_text: str,
        intent_json: str | None = None,
    ) -> int:
        """Append a turn to a session.

        Args:
            session_id: ID of the chat session
            role: 'user', 'assistant', or 'system'
            message_text: The message content
            intent_json: Optional parsed intent as JSON string

        Returns:
            turn_id
        """
        session = get_session()
        try:
            chat_session = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not chat_session:
                raise ChatSessionNotFoundError(f"Chat session {session_id} not found")

            # Get current turn count for index
            turn_count = (
                session.query(ChatTurn)
                .filter(ChatTurn.session_id == session_id)
                .count()
            )

            turn = ChatTurn(
                session_id=session_id,
                turn_index=turn_count,
                role=role,
                message_text=message_text,
                intent_json=intent_json,
            )
            session.add(turn)

            # Update session last_activity_at
            chat_session.last_activity_at = datetime.now(timezone.utc)

            session.commit()
            turn_id = turn.id
            logger.debug(f"Added turn {turn_id} to session {session_id}")
            return turn_id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_session(self, session_id: int) -> dict[str, Any] | None:
        """Get session with all turns.

        Returns:
            Dict with session metadata and turns list, or None if not found.
        """
        session = get_session()
        try:
            chat_session = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not chat_session:
                return None

            turns = (
                session.query(ChatTurn)
                .filter(ChatTurn.session_id == session_id)
                .order_by(ChatTurn.turn_index)
                .all()
            )

            return {
                "id": chat_session.id,
                "status": chat_session.status,
                "channel_type": chat_session.channel_type,
                "channel_session_key": chat_session.channel_session_key,
                "user_id": chat_session.user_id,
                "started_at": chat_session.started_at.isoformat() if chat_session.started_at else None,
                "last_activity_at": chat_session.last_activity_at.isoformat() if chat_session.last_activity_at else None,
                "ended_at": chat_session.ended_at.isoformat() if chat_session.ended_at else None,
                "context_json": chat_session.context_json,
                "turns": [
                    {
                        "id": t.id,
                        "turn_index": t.turn_index,
                        "role": t.role,
                        "message_text": t.message_text,
                        "intent_json": t.intent_json,
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                    }
                    for t in turns
                ],
            }
        finally:
            session.close()

    def end_session(self, session_id: int) -> None:
        """Close a session."""
        session = get_session()
        try:
            chat_session = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not chat_session:
                raise ChatSessionNotFoundError(f"Chat session {session_id} not found")

            chat_session.status = "closed"
            chat_session.ended_at = datetime.now(timezone.utc)
            session.commit()
            logger.info(f"Closed chat session {session_id}")
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
