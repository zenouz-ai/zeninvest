"""Conversational trading session API for US-1.9."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.agents.conversation.orchestrator import ConversationOrchestrator
from src.agents.conversation.session_manager import (
    ChatActionNotFoundError,
    ChatSessionNotFoundError,
    SessionManager,
)

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


class SessionActionRequest(BaseModel):
    channel_type: Literal["dashboard", "slack"] = "dashboard"


def _raise_server_error(exc: Exception) -> None:
    raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """List recent conversation sessions for the dashboard operator console."""
    try:
        return _orchestrator.list_sessions(limit=limit, status=status)
    except Exception as exc:
        _raise_server_error(exc)


@router.post("/sessions")
async def create_session(body: CreateSessionRequest) -> dict[str, Any]:
    """Create or resume a channel-bound conversational session."""
    try:
        return _orchestrator.start_session(
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
    result = _session_manager.get_session(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return result


@router.post("/sessions/{session_id}/turns")
async def submit_turn(session_id: int, body: SubmitTurnRequest) -> dict[str, Any]:
    """Submit a new conversational turn and return the refreshed session."""
    try:
        return _orchestrator.process_turn(
            session_id=session_id,
            message_text=body.message_text,
            channel_type=body.channel_type,
            user_id=body.user_id,
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
        return _orchestrator.confirm_action(
            session_id=session_id,
            action_id=action_id,
            channel_type=body.channel_type,
        )
    except (ChatSessionNotFoundError, ChatActionNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _raise_server_error(exc)


@router.post("/sessions/{session_id}/actions/{action_id}/reject")
async def reject_action(session_id: int, action_id: int, body: SessionActionRequest) -> dict[str, Any]:
    """Reject a pending conversational action and return the refreshed session."""
    try:
        return _orchestrator.reject_action(
            session_id=session_id,
            action_id=action_id,
            channel_type=body.channel_type,
        )
    except (ChatSessionNotFoundError, ChatActionNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
