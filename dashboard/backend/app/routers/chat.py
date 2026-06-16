"""Conversational trading session API for US-1.9."""

from __future__ import annotations

from typing import Any, Literal, Never

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.agents.conversation.orchestrator import ConversationOrchestrator
from src.agents.conversation.session_manager import (
    ChatActionNotFoundError,
    ChatSessionNotFoundError,
    SessionManager,
    StaleActionError,
)

from ..async_utils import run_blocking

router = APIRouter()

_session_manager = SessionManager()
_orchestrator = ConversationOrchestrator(session_manager=_session_manager)


class CreateSessionRequest(BaseModel):
    channel_type: Literal["dashboard", "slack"] = "dashboard"
    user_id: str | None = None
    channel_session_key: str | None = None
    title: str | None = None


class SubmitTurnRequest(BaseModel):
    message_text: str = Field(min_length=1)
    channel_type: Literal["dashboard", "slack"] = "dashboard"
    user_id: str | None = None
    mode: Literal["quick", "research", "committee", "trade"] | None = None
    budget_tier: Literal["standard", "premium"] | None = None


class SessionActionRequest(BaseModel):
    channel_type: Literal["dashboard", "slack"] = "dashboard"
    expected_version: int = Field(gt=0)


def _raise_server_error(exc: Exception) -> Never:
    raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    channel_type: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """List recent conversation sessions for the dashboard operator console."""
    try:
        sessions = _orchestrator.list_sessions(limit=limit, status=status)
        if channel_type:
            sessions = [s for s in sessions if s.get("channel_type") == channel_type]
        return sessions
    except Exception as exc:
        _raise_server_error(exc)


@router.post("/sessions")
async def create_session(body: CreateSessionRequest) -> dict[str, Any]:
    """Create or resume a channel-bound conversational session."""
    try:
        return await run_blocking(
            _orchestrator.start_session,
            channel_type=body.channel_type,
            user_id=body.user_id,
            channel_session_key=body.channel_session_key,
            title=body.title,
        )
    except Exception as exc:
        _raise_server_error(exc)


@router.get("/sessions/{session_id}")
async def get_session(session_id: int) -> dict[str, Any]:
    """Return full session detail including turns, actions, and research logs."""
    result = await run_blocking(_session_manager.get_session, session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return result


@router.post("/sessions/{session_id}/turns")
async def submit_turn(session_id: int, body: SubmitTurnRequest) -> dict[str, Any]:
    """Submit a new conversational turn and return the refreshed session."""
    try:
        return await run_blocking(
            _orchestrator.process_turn,
            session_id=session_id,
            message_text=body.message_text,
            channel_type=body.channel_type,
            user_id=body.user_id,
            mode=body.mode,
            budget_tier=body.budget_tier,
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _raise_server_error(exc)


@router.post("/sessions/{session_id}/actions/{action_id}/confirm")
async def confirm_action(session_id: int, action_id: int, body: SessionActionRequest) -> dict[str, Any]:
    """Confirm a pending conversational action and return the refreshed session."""
    try:
        return await run_blocking(
            _orchestrator.confirm_action,
            session_id=session_id,
            action_id=action_id,
            channel_type=body.channel_type,
            expected_version=body.expected_version,
        )
    except (ChatSessionNotFoundError, ChatActionNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StaleActionError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "action": exc.latest_action,
            },
        ) from exc
    except Exception as exc:
        _raise_server_error(exc)


@router.post("/sessions/{session_id}/actions/{action_id}/reject")
async def reject_action(session_id: int, action_id: int, body: SessionActionRequest) -> dict[str, Any]:
    """Reject a pending conversational action and return the refreshed session."""
    try:
        return await run_blocking(
            _orchestrator.reject_action,
            session_id=session_id,
            action_id=action_id,
            channel_type=body.channel_type,
            expected_version=body.expected_version,
        )
    except (ChatSessionNotFoundError, ChatActionNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StaleActionError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "action": exc.latest_action,
            },
        ) from exc
    except Exception as exc:
        _raise_server_error(exc)


@router.post("/sessions/{session_id}/end")
async def end_session(session_id: int) -> dict[str, Any]:
    """Close a conversational session."""
    try:
        _session_manager.end_session(session_id)
        return {"status": "closed", "session_id": session_id}
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _raise_server_error(exc)


# ---------------------------------------------------------------------------
# Phase 7: Extended chat API endpoints
# ---------------------------------------------------------------------------


@router.get("/sessions/{session_id}/turns")
async def list_turns(
    session_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Return paginated turns for a session."""
    try:
        return _session_manager.list_turns(session_id, offset=offset, limit=limit)
    except Exception as exc:
        _raise_server_error(exc)


@router.get("/sessions/{session_id}/actions")
async def list_actions(
    session_id: int,
    status: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """Return actions for a session, optionally filtered by status."""
    try:
        return _session_manager.list_actions(session_id, status=status)
    except Exception as exc:
        _raise_server_error(exc)


@router.get("/sessions/{session_id}/spend")
async def get_session_spend(session_id: int) -> dict[str, Any]:
    """Return cost summary for a session."""
    try:
        return _session_manager.get_session_spend(session_id)
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _raise_server_error(exc)


@router.delete("/sessions/{session_id}")
async def archive_session(session_id: int) -> dict[str, Any]:
    """Soft-delete (archive) a session."""
    try:
        _session_manager.archive_session(session_id)
        return {"status": "archived", "session_id": session_id}
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _raise_server_error(exc)
