"""Chat session API stubs for conversational trading workflow (US-1.9 skeleton).

Provides minimal CRUD endpoints for chat sessions and turns.
No LLM logic, no execution — just plumbing for future conversational workflow.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.agents.conversation.session_manager import SessionManager

router = APIRouter()

_session_manager = SessionManager()


class CreateSessionRequest(BaseModel):
    channel_type: str = "dashboard"
    user_id: str | None = None
    channel_session_key: str | None = None


class AddTurnRequest(BaseModel):
    role: str = "user"
    message_text: str = ""
    intent_json: str | None = None


@router.post("/sessions")
async def create_session(body: CreateSessionRequest) -> dict[str, Any]:
    """Create a new chat session."""
    try:
        session_id = _session_manager.create_session(
            channel_type=body.channel_type,
            user_id=body.user_id,
            channel_session_key=body.channel_session_key,
        )
        return {"status": "created", "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/turns")
async def add_turn(session_id: int, body: AddTurnRequest) -> dict[str, Any]:
    """Add a turn to a session."""
    try:
        turn_id = _session_manager.add_turn(
            session_id=session_id,
            role=body.role,
            message_text=body.message_text,
            intent_json=body.intent_json,
        )
        return {"status": "received", "turn_id": turn_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}")
async def get_session(session_id: int) -> dict[str, Any]:
    """Get session with turns."""
    result = _session_manager.get_session(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return result


@router.post("/sessions/{session_id}/end")
async def end_session(session_id: int) -> dict[str, Any]:
    """Close a session."""
    try:
        _session_manager.end_session(session_id)
        return {"status": "closed", "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
