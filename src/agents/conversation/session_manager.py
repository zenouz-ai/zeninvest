"""Persistence helpers for conversational trading workflow (US-1.9)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func

from src.agents.conversation.context import SessionContext
from src.data.database import get_session
from src.data.models import (
    ChatAction,
    ChatResearchLog,
    ChatSession,
    ChatTurn,
    ChatWorkflowStep,
    CostLog,
    ResearchLog,
)
from src.utils.datetime_utils import ensure_utc_datetime
from src.utils.logger import get_logger

logger = get_logger("session_manager")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _json_loads(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


class ChatSessionNotFoundError(LookupError):
    """Raised when a requested chat session does not exist."""


class ChatActionNotFoundError(LookupError):
    """Raised when a requested chat action does not exist."""


class StaleActionError(Exception):
    """Raised when an action's version has changed (optimistic concurrency)."""

    def __init__(self, message: str, *, latest_action: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.latest_action = latest_action


class SessionManager:
    """Manages conversational trading session lifecycle and audit persistence."""

    def create_session(
        self,
        channel_type: str,
        user_id: str | None = None,
        channel_session_key: str | None = None,
        *,
        title: str | None = None,
        resume_if_exists: bool = True,
    ) -> int:
        """Create a new session or resume an active channel-bound session."""
        session = get_session()
        try:
            existing: ChatSession | None = None
            if resume_if_exists and channel_session_key:
                existing = (
                    session.query(ChatSession)
                    .filter(
                        ChatSession.channel_type == channel_type,
                        ChatSession.channel_session_key == channel_session_key,
                        ChatSession.status == "active",
                    )
                    .order_by(ChatSession.id.desc())
                    .first()
                )

            if existing is not None:
                existing.last_activity_at = _utcnow()
                existing.last_channel_type = channel_type
                if user_id and not existing.user_id:
                    existing.user_id = user_id
                session.commit()
                logger.info("Resumed chat session %s (%s)", existing.id, channel_type)
                return int(existing.id)

            inherited_context: dict[str, Any] | None = None
            previous_session_id: int | None = None
            if user_id:
                previous_session = (
                    session.query(ChatSession)
                    .filter(
                        ChatSession.channel_type == channel_type,
                        ChatSession.user_id == user_id,
                    )
                    .order_by(ChatSession.last_activity_at.desc(), ChatSession.id.desc())
                    .first()
                )
                if previous_session is not None:
                    previous_context = SessionContext.from_json(_json_loads(previous_session.context_json))
                    inherited = SessionContext()
                    inherited.inherit_from(previous_context)
                    inherited.previous_session_id = int(previous_session.id)
                    inherited_context = inherited.to_dict()
                    previous_session_id = int(previous_session.id)

            chat_session = ChatSession(
                status="active",
                channel_type=channel_type,
                channel_session_key=channel_session_key,
                user_id=user_id,
                title=title,
                last_channel_type=channel_type,
                context_json=_json_dumps(inherited_context),
                previous_session_id=previous_session_id,
            )
            session.add(chat_session)
            session.commit()
            session_id = int(chat_session.id)
            logger.info("Created chat session %s (%s)", session_id, channel_type)
            return session_id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def find_active_session(
        self,
        *,
        channel_type: str,
        channel_session_key: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Find the current active session for a channel/session key or fallback user."""
        session = get_session()
        try:
            query = session.query(ChatSession).filter(ChatSession.status == "active")
            if channel_session_key:
                query = query.filter(
                    ChatSession.channel_type == channel_type,
                    ChatSession.channel_session_key == channel_session_key,
                )
            elif user_id:
                query = query.filter(ChatSession.user_id == user_id)
            else:
                return None

            match = query.order_by(ChatSession.last_activity_at.desc(), ChatSession.id.desc()).first()
            if not match:
                return None
            return self._serialize_session_summary(match, session)
        finally:
            session.close()

    def list_sessions(
        self,
        *,
        limit: int = 50,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List recent conversation sessions for the operator console."""
        session = get_session()
        try:
            query = session.query(ChatSession)
            if status:
                query = query.filter(ChatSession.status == status)
            rows = (
                query.order_by(ChatSession.last_activity_at.desc(), ChatSession.id.desc())
                .limit(limit)
                .all()
            )
            return [self._serialize_session_summary(row, session) for row in rows]
        finally:
            session.close()

    def add_turn(
        self,
        session_id: int,
        role: str,
        message_text: str,
        intent_json: Any | None = None,
        *,
        resolution_json: Any | None = None,
        response_json: Any | None = None,
        channel_type: str | None = None,
    ) -> int:
        """Append a turn to a session and update session activity metadata."""
        session = get_session()
        try:
            chat_session = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not chat_session:
                raise ChatSessionNotFoundError(f"Chat session {session_id} not found")

            turn_count = session.query(ChatTurn).filter(ChatTurn.session_id == session_id).count()
            turn = ChatTurn(
                session_id=session_id,
                turn_index=turn_count,
                role=role,
                channel_type=channel_type,
                message_text=message_text,
                intent_json=_json_dumps(intent_json),
                resolution_json=_json_dumps(resolution_json),
                response_json=_json_dumps(response_json),
            )
            session.add(turn)
            chat_session.last_activity_at = _utcnow()
            if channel_type:
                chat_session.last_channel_type = channel_type
            if not chat_session.title and role == "user" and message_text:
                chat_session.title = message_text[:120]

            session.commit()
            return int(turn.id)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_action(
        self,
        *,
        session_id: int,
        turn_id: int | None,
        action_type: str,
        status: str,
        title: str | None = None,
        ticker: str | None = None,
        payload_json: Any | None = None,
        preview_text: str | None = None,
        result_json: Any | None = None,
        requires_confirmation: bool = False,
        rejection_reason: str | None = None,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Create a new action ledger row for a session."""
        session = get_session()
        try:
            chat_session = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not chat_session:
                raise ChatSessionNotFoundError(f"Chat session {session_id} not found")

            action = ChatAction(
                session_id=session_id,
                turn_id=turn_id,
                action_type=action_type,
                status=status,
                title=title,
                ticker=ticker,
                payload_json=_json_dumps(payload_json),
                preview_text=preview_text,
                result_json=_json_dumps(result_json),
                requires_confirmation=requires_confirmation,
                rejection_reason=rejection_reason,
                expires_at=ensure_utc_datetime(expires_at),
            )
            session.add(action)
            chat_session.last_activity_at = _utcnow()
            session.commit()
            return self._serialize_action(action)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_action(
        self,
        action_id: int,
        *,
        status: str | None = None,
        preview_text: str | None = None,
        result_json: Any | None = None,
        rejection_reason: str | None = None,
        confirmed_at: datetime | None = None,
        executed_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Update action state and return the serialized row."""
        session = get_session()
        try:
            action = session.query(ChatAction).filter(ChatAction.id == action_id).first()
            if not action:
                raise ChatActionNotFoundError(f"Chat action {action_id} not found")
            if status is not None:
                action.status = status
            if preview_text is not None:
                action.preview_text = preview_text
            if result_json is not None:
                action.result_json = _json_dumps(result_json)
            if rejection_reason is not None:
                action.rejection_reason = rejection_reason
            if confirmed_at is not None:
                action.confirmed_at = ensure_utc_datetime(confirmed_at)
            if executed_at is not None:
                action.executed_at = ensure_utc_datetime(executed_at)
            if expires_at is not None:
                action.expires_at = ensure_utc_datetime(expires_at)
            session.commit()
            return self._serialize_action(action)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def add_workflow_step(
        self,
        *,
        session_id: int,
        turn_id: int | None,
        step_key: str,
        status: str = "running",
        label: str | None = None,
        detail: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tool_name: str | None = None,
        cost_gbp: float | None = None,
        latency_ms: float | None = None,
        detail_json: Any | None = None,
        completed_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Persist a workflow step for a conversational turn."""
        session = get_session()
        try:
            row = ChatWorkflowStep(
                session_id=session_id,
                turn_id=turn_id,
                step_key=step_key,
                status=status,
                label=label,
                detail=detail,
                provider=provider,
                model=model,
                tool_name=tool_name,
                cost_gbp=cost_gbp,
                latency_ms=latency_ms,
                detail_json=_json_dumps(detail_json),
                completed_at=completed_at,
            )
            session.add(row)
            chat_session = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if chat_session:
                chat_session.last_activity_at = _utcnow()
            session.commit()
            return self._serialize_workflow_step(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_workflow_step(
        self,
        step_id: int,
        *,
        status: str | None = None,
        detail: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tool_name: str | None = None,
        cost_gbp: float | None = None,
        latency_ms: float | None = None,
        detail_json: Any | None = None,
        completed_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Update a persisted workflow step."""
        session = get_session()
        try:
            row = session.query(ChatWorkflowStep).filter(ChatWorkflowStep.id == step_id).first()
            if row is None:
                raise ChatSessionNotFoundError(f"Workflow step {step_id} not found")
            if status is not None:
                row.status = status
            if detail is not None:
                row.detail = detail
            if provider is not None:
                row.provider = provider
            if model is not None:
                row.model = model
            if tool_name is not None:
                row.tool_name = tool_name
            if cost_gbp is not None:
                row.cost_gbp = cost_gbp
            if latency_ms is not None:
                row.latency_ms = latency_ms
            if detail_json is not None:
                row.detail_json = _json_dumps(detail_json)
            if completed_at is not None:
                row.completed_at = completed_at
            session.commit()
            return self._serialize_workflow_step(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_pending_action(self, session_id: int) -> dict[str, Any] | None:
        """Return the most recent unexpired action awaiting confirmation."""
        session = get_session()
        try:
            now = _utcnow()
            row = (
                session.query(ChatAction)
                .filter(
                    ChatAction.session_id == session_id,
                    ChatAction.status == "awaiting_confirmation",
                )
                .order_by(ChatAction.created_at.desc(), ChatAction.id.desc())
                .first()
            )
            if row is None:
                return None
            expires_at = ensure_utc_datetime(row.expires_at)
            if expires_at and expires_at < now:
                row.status = "expired"
                row.rejection_reason = "Confirmation expired."
                session.commit()
            return self._serialize_action(row)
        finally:
            session.close()

    def list_pending_actions(self, session_id: int) -> list[dict[str, Any]]:
        session = get_session()
        try:
            rows = (
                session.query(ChatAction)
                .filter(
                    ChatAction.session_id == session_id,
                    ChatAction.status.in_(["awaiting_confirmation", "confirmed", "executing"]),
                )
                .order_by(ChatAction.created_at.desc(), ChatAction.id.desc())
                .all()
            )
            return [self._serialize_action(row) for row in rows]
        finally:
            session.close()

    def add_research_log(
        self,
        *,
        session_id: int,
        turn_id: int | None,
        tool_name: str,
        provider: str | None = None,
        query: str | None = None,
        result_summary: str | None = None,
        cache_hit: bool = False,
        latency_ms: float | None = None,
    ) -> dict[str, Any]:
        """Persist a research trace row for a conversational turn."""
        session = get_session()
        try:
            row = ChatResearchLog(
                session_id=session_id,
                turn_id=turn_id,
                tool_name=tool_name,
                provider=provider,
                query=query,
                result_summary=result_summary,
                cache_hit=cache_hit,
                latency_ms=latency_ms,
            )
            session.add(row)
            session.commit()
            return self._serialize_research_log(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_session_context(
        self,
        session_id: int,
        *,
        context_json: Any | None = None,
        linked_cycle_id: str | None = None,
        title: str | None = None,
        last_channel_type: str | None = None,
    ) -> None:
        session = get_session()
        try:
            row = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not row:
                raise ChatSessionNotFoundError(f"Chat session {session_id} not found")
            if context_json is not None:
                row.context_json = _json_dumps(context_json)
            if linked_cycle_id is not None:
                row.linked_cycle_id = linked_cycle_id
            if title is not None:
                row.title = title
            if last_channel_type is not None:
                row.last_channel_type = last_channel_type
            row.last_activity_at = _utcnow()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_session(self, session_id: int) -> dict[str, Any] | None:
        """Get a full session detail including turns, actions, and research logs."""
        session = get_session()
        try:
            row = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not row:
                return None
            return self._serialize_session_detail(row, session)
        finally:
            session.close()

    def update_action_versioned(
        self,
        action_id: int,
        expected_version: int,
        *,
        status: str | None = None,
        result_json: Any | None = None,
        rejection_reason: str | None = None,
        confirmed_at: datetime | None = None,
        executed_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Optimistic-concurrency update: only succeeds when version matches.

        Raises ``StaleActionError`` if the action has been modified by a
        concurrent writer since the caller last read it.
        """
        session = get_session()
        try:
            action = session.query(ChatAction).filter(ChatAction.id == action_id).first()
            if not action:
                raise ChatActionNotFoundError(f"Chat action {action_id} not found")
            if action.version != expected_version:
                raise StaleActionError(
                    f"Action {action_id} version mismatch: expected {expected_version}, "
                    f"found {action.version}",
                    latest_action=self._serialize_action(action),
                )
            if status is not None:
                action.status = status
            if result_json is not None:
                action.result_json = _json_dumps(result_json)
            if rejection_reason is not None:
                action.rejection_reason = rejection_reason
            if confirmed_at is not None:
                action.confirmed_at = ensure_utc_datetime(confirmed_at)
            if executed_at is not None:
                action.executed_at = ensure_utc_datetime(executed_at)
            action.version += 1
            session.commit()
            return self._serialize_action(action)
        except (StaleActionError, ChatActionNotFoundError):
            session.rollback()
            raise
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def expire_old_pending_actions(self) -> int:
        """Expire all stale pending actions across sessions."""
        session = get_session()
        try:
            now = _utcnow()
            rows = (
                session.query(ChatAction)
                .filter(
                    ChatAction.status == "awaiting_confirmation",
                    ChatAction.expires_at.isnot(None),
                )
                .all()
            )
            for row in rows:
                expires_at = ensure_utc_datetime(row.expires_at)
                if expires_at and expires_at < now:
                    row.status = "expired"
                    row.rejection_reason = "Confirmation expired."
            if rows:
                session.commit()
            return len([row for row in rows if row.status == "expired"])
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_turns(
        self,
        session_id: int,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return paginated turns for a session."""
        session = get_session()
        try:
            turns = (
                session.query(ChatTurn)
                .filter(ChatTurn.session_id == session_id)
                .order_by(ChatTurn.turn_index.asc(), ChatTurn.id.asc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [self._serialize_turn(t) for t in turns]
        finally:
            session.close()

    def list_actions(
        self,
        session_id: int,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return actions for a session, optionally filtered by status."""
        session = get_session()
        try:
            query = session.query(ChatAction).filter(ChatAction.session_id == session_id)
            if status:
                query = query.filter(ChatAction.status == status)
            actions = query.order_by(ChatAction.created_at.desc(), ChatAction.id.desc()).all()
            return [self._serialize_action(a) for a in actions]
        finally:
            session.close()

    def get_session_spend(self, session_id: int) -> dict[str, Any]:
        """Return cost summary for a session."""
        session = get_session()
        try:
            row = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not row:
                raise ChatSessionNotFoundError(f"Chat session {session_id} not found")
            return self._serialize_cost_summary(session_id, session)
        finally:
            session.close()

    def archive_session(self, session_id: int) -> None:
        """Soft-delete a session by setting status to 'archived'."""
        session = get_session()
        try:
            chat_session = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not chat_session:
                raise ChatSessionNotFoundError(f"Chat session {session_id} not found")
            chat_session.status = "archived"
            chat_session.ended_at = _utcnow()
            chat_session.last_activity_at = _utcnow()
            session.commit()
        except Exception:
            session.rollback()
            raise
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
            chat_session.ended_at = _utcnow()
            chat_session.last_activity_at = _utcnow()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _serialize_session_summary(self, row: ChatSession, session: Any) -> dict[str, Any]:
        last_turn = (
            session.query(ChatTurn)
            .filter(ChatTurn.session_id == row.id)
            .order_by(ChatTurn.turn_index.desc(), ChatTurn.id.desc())
            .first()
        )
        pending_count = (
            session.query(ChatAction)
            .filter(
                ChatAction.session_id == row.id,
                ChatAction.status.in_(["awaiting_confirmation", "confirmed", "executing"]),
            )
            .count()
        )
        return {
            "id": row.id,
            "status": row.status,
            "channel_type": row.channel_type,
            "channel_session_key": row.channel_session_key,
            "last_channel_type": row.last_channel_type or row.channel_type,
            "user_id": row.user_id,
            "title": row.title,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "last_activity_at": row.last_activity_at.isoformat() if row.last_activity_at else None,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "linked_cycle_id": row.linked_cycle_id,
            "last_message_text": last_turn.message_text if last_turn else None,
            "last_message_role": last_turn.role if last_turn else None,
            "pending_actions_count": pending_count,
        }

    def _serialize_turn(self, turn: ChatTurn) -> dict[str, Any]:
        return {
            "id": turn.id,
            "session_id": turn.session_id,
            "turn_index": turn.turn_index,
            "role": turn.role,
            "channel_type": turn.channel_type,
            "message_text": turn.message_text,
            "intent_json": _json_loads(turn.intent_json),
            "resolution_json": _json_loads(turn.resolution_json),
            "response_json": _json_loads(turn.response_json),
            "created_at": turn.created_at.isoformat() if turn.created_at else None,
        }

    def _serialize_action(self, row: ChatAction) -> dict[str, Any]:
        expires_at = ensure_utc_datetime(row.expires_at)
        confirmed_at = ensure_utc_datetime(row.confirmed_at)
        executed_at = ensure_utc_datetime(row.executed_at)
        created_at = ensure_utc_datetime(row.created_at)
        updated_at = ensure_utc_datetime(row.updated_at)
        return {
            "id": row.id,
            "session_id": row.session_id,
            "turn_id": row.turn_id,
            "action_type": row.action_type,
            "status": row.status,
            "title": row.title,
            "ticker": row.ticker,
            "payload_json": _json_loads(row.payload_json),
            "preview_text": row.preview_text,
            "result_json": _json_loads(row.result_json),
            "requires_confirmation": bool(row.requires_confirmation),
            "rejection_reason": row.rejection_reason,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "confirmed_at": confirmed_at.isoformat() if confirmed_at else None,
            "executed_at": executed_at.isoformat() if executed_at else None,
            "created_at": created_at.isoformat() if created_at else None,
            "updated_at": updated_at.isoformat() if updated_at else None,
            "version": getattr(row, "version", 1),
        }

    def _serialize_research_log(self, row: ChatResearchLog) -> dict[str, Any]:
        return {
            "id": row.id,
            "session_id": row.session_id,
            "turn_id": row.turn_id,
            "tool_name": row.tool_name,
            "provider": row.provider,
            "query": row.query,
            "result_summary": row.result_summary,
            "cache_hit": bool(row.cache_hit),
            "latency_ms": row.latency_ms,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def _serialize_workflow_step(self, row: ChatWorkflowStep) -> dict[str, Any]:
        return {
            "id": row.id,
            "session_id": row.session_id,
            "turn_id": row.turn_id,
            "step_key": row.step_key,
            "status": row.status,
            "label": row.label,
            "detail": row.detail,
            "provider": row.provider,
            "model": row.model,
            "tool_name": row.tool_name,
            "cost_gbp": row.cost_gbp,
            "latency_ms": row.latency_ms,
            "detail_json": _json_loads(row.detail_json),
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _serialize_session_detail(self, row: ChatSession, session: Any) -> dict[str, Any]:
        turns = (
            session.query(ChatTurn)
            .filter(ChatTurn.session_id == row.id)
            .order_by(ChatTurn.turn_index.asc(), ChatTurn.id.asc())
            .all()
        )
        actions = (
            session.query(ChatAction)
            .filter(ChatAction.session_id == row.id)
            .order_by(ChatAction.created_at.desc(), ChatAction.id.desc())
            .all()
        )
        research_logs = (
            session.query(ChatResearchLog)
            .filter(ChatResearchLog.session_id == row.id)
            .order_by(ChatResearchLog.created_at.desc(), ChatResearchLog.id.desc())
            .all()
        )
        workflow_steps = (
            session.query(ChatWorkflowStep)
            .filter(ChatWorkflowStep.session_id == row.id)
            .order_by(ChatWorkflowStep.started_at.asc(), ChatWorkflowStep.id.asc())
            .all()
        )
        summary = self._serialize_session_summary(row, session)
        summary["context_json"] = _json_loads(row.context_json)
        summary["turns"] = [self._serialize_turn(turn) for turn in turns]
        summary["actions"] = [self._serialize_action(action) for action in actions]
        summary["research_logs"] = [self._serialize_research_log(log) for log in research_logs]
        summary["workflow_steps"] = [self._serialize_workflow_step(step) for step in workflow_steps]
        summary["cost_summary"] = self._serialize_cost_summary(int(row.id), session)
        latest_assistant = next(
            (
                turn
                for turn in reversed(summary["turns"])
                if turn.get("role") == "assistant"
            ),
            None,
        )
        latest_response = latest_assistant.get("response_json") if isinstance(latest_assistant, dict) else None
        if not isinstance(latest_response, dict):
            latest_response = {}
        summary["turn_mode"] = latest_response.get("turn_mode")
        summary["evidence_blocks"] = latest_response.get("evidence_blocks")
        summary["citations"] = latest_response.get("citations") or []
        summary["related_tickers"] = latest_response.get("related_tickers") or []
        summary["committee_views"] = latest_response.get("committee_views") or []
        summary["confidence"] = latest_response.get("confidence")
        summary["next_actions"] = latest_response.get("next_actions") or []
        summary["warnings"] = latest_response.get("warnings") or []
        return summary

    def session_cost_total_gbp(self, session_id: int) -> float:
        """Return the current total chat-attributed cost for a session."""
        session = get_session()
        try:
            return self._serialize_cost_summary(session_id, session)["total_cost_gbp"]
        finally:
            session.close()

    def _serialize_cost_summary(self, session_id: int, session: Any) -> dict[str, Any]:
        llm_rows = (
            session.query(
                CostLog.provider,
                CostLog.model,
                func.count(CostLog.id).label("calls"),
                func.coalesce(func.sum(CostLog.cost_gbp), 0.0).label("cost_gbp"),
            )
            .filter(CostLog.chat_session_id == session_id)
            .group_by(CostLog.provider, CostLog.model)
            .all()
        )
        research_rows = (
            session.query(
                ResearchLog.provider,
                func.count(ResearchLog.id).label("calls"),
                func.coalesce(func.sum(ResearchLog.cost_usd), 0.0).label("cost_usd"),
            )
            .filter(ResearchLog.chat_session_id == session_id)
            .group_by(ResearchLog.provider)
            .all()
        )

        llm_calls = 0
        llm_cost_gbp = 0.0
        by_provider_gbp: dict[str, float] = {}
        by_model_gbp: dict[str, float] = {}
        for provider, model, calls, cost_gbp in llm_rows:
            provider_key = str(provider or "unknown")
            model_key = str(model or "unknown")
            calls_int = int(calls or 0)
            cost_value = round(float(cost_gbp or 0.0), 4)
            llm_calls += calls_int
            llm_cost_gbp += cost_value
            by_provider_gbp[provider_key] = round(by_provider_gbp.get(provider_key, 0.0) + cost_value, 4)
            by_model_gbp[model_key] = round(by_model_gbp.get(model_key, 0.0) + cost_value, 4)

        research_calls = 0
        research_cost_usd = 0.0
        research_by_provider_gbp: dict[str, float] = {}
        for provider, calls, cost_usd in research_rows:
            provider_key = str(provider or "unknown")
            calls_int = int(calls or 0)
            usd_value = float(cost_usd or 0.0)
            gbp_value = round(usd_value * 0.79, 4)
            research_calls += calls_int
            research_cost_usd += usd_value
            research_by_provider_gbp[provider_key] = round(
                research_by_provider_gbp.get(provider_key, 0.0) + gbp_value,
                4,
            )

        research_cost_gbp = round(research_cost_usd * 0.79, 4)
        llm_cost_gbp = round(llm_cost_gbp, 4)
        return {
            "llm_calls": llm_calls,
            "llm_cost_gbp": llm_cost_gbp,
            "research_calls": research_calls,
            "research_cost_usd": round(research_cost_usd, 4),
            "research_cost_gbp": research_cost_gbp,
            "total_cost_gbp": round(llm_cost_gbp + research_cost_gbp, 4),
            "by_provider_gbp": by_provider_gbp,
            "by_model_gbp": by_model_gbp,
            "research_by_provider_gbp": research_by_provider_gbp,
        }
