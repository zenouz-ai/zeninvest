"""Context-local chat cost attribution helpers."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator


_chat_session_id_var: ContextVar[int | None] = ContextVar("chat_session_id", default=None)
_chat_turn_id_var: ContextVar[int | None] = ContextVar("chat_turn_id", default=None)


def current_chat_cost_context() -> tuple[int | None, int | None]:
    """Return the current chat session/turn attribution tuple."""
    return _chat_session_id_var.get(), _chat_turn_id_var.get()


@contextmanager
def bind_chat_cost_context(*, session_id: int | None, turn_id: int | None) -> Iterator[None]:
    """Bind chat attribution to the current execution context for nested writes."""
    session_token: Token[int | None] = _chat_session_id_var.set(session_id)
    turn_token: Token[int | None] = _chat_turn_id_var.set(turn_id)
    try:
        yield
    finally:
        _chat_session_id_var.reset(session_token)
        _chat_turn_id_var.reset(turn_token)
