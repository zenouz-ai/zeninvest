"""Typed session context for conversational trading (US-1.9 Phase 3).

Replaces the untyped ``context_json`` dict with a structured ``SessionContext``
that supports serialization, merging, compaction, and cross-session inheritance.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TickerContext:
    """Per-ticker state carried across turns."""

    ticker: str
    last_mentioned_turn: int = 0
    last_action: str | None = None  # BUY, SELL, REVIEW, etc.
    data_snapshot_summary: str | None = None  # brief textual summary

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TickerContext:
        return cls(
            ticker=d["ticker"],
            last_mentioned_turn=d.get("last_mentioned_turn", 0),
            last_action=d.get("last_action"),
            data_snapshot_summary=d.get("data_snapshot_summary"),
        )


@dataclass
class SessionContext:
    """Typed session context persisted as ``chat_sessions.context_json``.

    Every intent handler returns a partial ``SessionContext`` via
    ``context_update``; the orchestrator merges it with the previous state
    before persisting.
    """

    # Ticker tracking
    active_tickers: dict[str, TickerContext] = field(default_factory=dict)
    watchlist: list[str] = field(default_factory=list)
    last_subject_tickers: list[str] = field(default_factory=list)
    last_selection_tickers: list[str] = field(default_factory=list)
    last_selection_result: dict[str, Any] | None = None

    # Pending actions (action IDs awaiting confirmation)
    pending_actions: list[int] = field(default_factory=list)

    # Turn tracking
    turn_count: int = 0
    last_compacted_at_turn: int = 0

    # Summary from compaction
    conversation_summary: str = ""

    # Portfolio snapshot at session start (for delta comparisons)
    portfolio_snapshot_at_start: dict[str, Any] | None = None

    # Previous session linkage
    previous_session_id: int | None = None

    # ---- Serialization ----

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "active_tickers": {k: v.to_dict() for k, v in self.active_tickers.items()},
            "watchlist": self.watchlist,
            "last_subject_tickers": self.last_subject_tickers,
            "last_selection_tickers": self.last_selection_tickers,
            "last_selection_result": self.last_selection_result,
            "pending_actions": self.pending_actions,
            "turn_count": self.turn_count,
            "last_compacted_at_turn": self.last_compacted_at_turn,
            "conversation_summary": self.conversation_summary,
            "portfolio_snapshot_at_start": self.portfolio_snapshot_at_start,
            "previous_session_id": self.previous_session_id,
        }
        return d

    @classmethod
    def from_json(cls, raw: str | dict[str, Any] | None) -> SessionContext:
        """Deserialize from JSON string or dict.  Gracefully handles legacy
        untyped dicts that only have ``last_subject_tickers`` etc."""
        if raw is None:
            return cls()
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return cls()
        if not isinstance(raw, dict):
            return cls()

        active_tickers: dict[str, TickerContext] = {}
        for k, v in (raw.get("active_tickers") or {}).items():
            if isinstance(v, dict):
                active_tickers[k] = TickerContext.from_dict(v)

        return cls(
            active_tickers=active_tickers,
            watchlist=raw.get("watchlist") or [],
            last_subject_tickers=raw.get("last_subject_tickers") or [],
            last_selection_tickers=raw.get("last_selection_tickers") or [],
            last_selection_result=raw.get("last_selection_result"),
            pending_actions=raw.get("pending_actions") or [],
            turn_count=raw.get("turn_count", 0),
            last_compacted_at_turn=raw.get("last_compacted_at_turn", 0),
            conversation_summary=raw.get("conversation_summary", ""),
            portfolio_snapshot_at_start=raw.get("portfolio_snapshot_at_start"),
            previous_session_id=raw.get("previous_session_id"),
        )

    # ---- Merging ----

    def merge(self, update: dict[str, Any]) -> None:
        """Merge a partial update dict into this context.

        Handles both new-style ``SessionContext`` fields and legacy
        ``last_subject_tickers`` / ``last_selection_tickers`` keys.
        """
        if not update:
            return

        if "last_subject_tickers" in update:
            self.last_subject_tickers = update["last_subject_tickers"]
        if "last_selection_tickers" in update:
            self.last_selection_tickers = update["last_selection_tickers"]
        if "last_selection_result" in update:
            self.last_selection_result = update["last_selection_result"]
        if "watchlist" in update:
            self.watchlist = update["watchlist"]
        if "pending_actions" in update:
            self.pending_actions = update["pending_actions"]
        if "conversation_summary" in update:
            self.conversation_summary = update["conversation_summary"]
        if "portfolio_snapshot_at_start" in update:
            self.portfolio_snapshot_at_start = update["portfolio_snapshot_at_start"]

        # Merge active_tickers (additive, newer overwrites)
        for k, v in (update.get("active_tickers") or {}).items():
            if isinstance(v, TickerContext):
                self.active_tickers[k] = v
            elif isinstance(v, dict):
                self.active_tickers[k] = TickerContext.from_dict(v)

        # Auto-promote mentioned tickers into active_tickers
        for t in self.last_subject_tickers:
            if t and t not in self.active_tickers:
                self.active_tickers[t] = TickerContext(
                    ticker=t, last_mentioned_turn=self.turn_count
                )
            elif t in self.active_tickers:
                self.active_tickers[t].last_mentioned_turn = self.turn_count

    def increment_turn(self) -> None:
        self.turn_count += 1

    # ---- Compaction ----

    def needs_compaction(self, interval: int = 5) -> bool:
        """Return True if enough turns have elapsed since last compaction."""
        return (self.turn_count - self.last_compacted_at_turn) >= interval

    def compact(self, summary: str) -> None:
        """Apply a compacted summary, keeping all ticker references."""
        self.conversation_summary = summary
        self.last_compacted_at_turn = self.turn_count

    # ---- Cross-session inheritance ----

    def inherit_from(self, previous: SessionContext) -> None:
        """Load relevant state from a previous session."""
        self.previous_session_id = None  # will be set by caller with actual ID
        # Inherit active tickers and watchlist
        for k, v in previous.active_tickers.items():
            if k not in self.active_tickers:
                self.active_tickers[k] = v
        if not self.watchlist and previous.watchlist:
            self.watchlist = list(previous.watchlist)

    def clear_inherited(self) -> None:
        """User requested 'start fresh' — drop inherited state."""
        self.active_tickers.clear()
        self.watchlist.clear()
        self.last_subject_tickers.clear()
        self.last_selection_tickers.clear()
        self.last_selection_result = None
        self.conversation_summary = ""
        self.previous_session_id = None

    # ---- Legacy compatibility ----

    def to_legacy_dict(self) -> dict[str, Any]:
        """Return the minimal dict that legacy handlers expect."""
        return {
            "last_subject_tickers": self.last_subject_tickers,
            "last_selection_tickers": self.last_selection_tickers,
        }
