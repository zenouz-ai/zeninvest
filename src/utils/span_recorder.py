"""Nested span recorder extending PhaseTimer for step_timing and latency_spans."""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from src.utils.phase_timer import PhaseTimer


class SpanRecorder(PhaseTimer):
    """Record pipeline phases (PhaseTimer) plus nested steps and span rows."""

    def __init__(self, *, slow_threshold_seconds: float = 1.0) -> None:
        super().__init__()
        self._steps: dict[str, float] = {}
        self._span_rows: list[dict[str, Any]] = []
        self._slow_threshold_seconds = slow_threshold_seconds
        self._slow_steps: list[dict[str, Any]] = []

    @contextmanager
    def span(self, name: str, *, parent: str | None = None) -> Iterator[None]:
        """Context manager for a named step; accumulates into step_timing."""
        started_at = datetime.now(timezone.utc)
        t0 = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - t0
            finished_at = datetime.now(timezone.utc)
            self.record_step(name, elapsed, parent=parent, started_at=started_at, finished_at=finished_at)

    def record_step(
        self,
        name: str,
        seconds: float,
        *,
        parent: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if seconds <= 0:
            return
        self._steps[name] = round(self._steps.get(name, 0.0) + seconds, 3)
        if started_at is None:
            started_at = datetime.now(timezone.utc)
        if finished_at is None:
            finished_at = datetime.now(timezone.utc)
        row = {
            "span_name": name,
            "parent_span": parent,
            "started_at": started_at,
            "completed_at": finished_at,
            "duration_ms": round(seconds * 1000, 1),
            "metadata_json": metadata,
        }
        self._span_rows.append(row)
        if seconds >= self._slow_threshold_seconds:
            self._slow_steps.append(
                {
                    "step": name,
                    "duration_ms": round(seconds * 1000, 1),
                    "parent": parent,
                }
            )

    def to_step_dict(self) -> dict[str, float]:
        """Return accumulated step seconds for summary_json.step_timing."""
        self.end()
        return dict(self._steps)

    def span_rows(self) -> list[dict[str, Any]]:
        """Return span rows for persistence to latency_spans."""
        self.end()
        return list(self._span_rows)

    def slow_steps(self) -> list[dict[str, Any]]:
        self.end()
        return list(self._slow_steps)
