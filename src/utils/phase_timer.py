"""Lightweight per-phase cycle timing for runs.summary_json."""

from __future__ import annotations

from datetime import datetime, timezone


class PhaseTimer:
    """Record start/end timestamps and elapsed seconds per named phase."""

    def __init__(self) -> None:
        self._phases: dict[str, dict[str, float | str]] = {}
        self._current: str | None = None
        self._started_at: datetime | None = None
        self._accumulated: dict[str, float] = {}

    def start(self, name: str) -> None:
        """Begin a wall-clock phase (ends any prior open phase)."""
        self.end()
        self._current = name
        self._started_at = datetime.now(timezone.utc)

    def end(self) -> None:
        """Close the currently open wall-clock phase, if any."""
        if self._current is None or self._started_at is None:
            return
        finished_at = datetime.now(timezone.utc)
        elapsed = (finished_at - self._started_at).total_seconds()
        self._record_phase(self._current, self._started_at, finished_at, elapsed)
        self._current = None
        self._started_at = None

    def add_elapsed(self, name: str, seconds: float) -> None:
        """Accumulate elapsed seconds for a phase (e.g. per-decision work in a loop)."""
        if seconds <= 0:
            return
        self._accumulated[name] = self._accumulated.get(name, 0.0) + seconds

    def to_dict(self) -> dict[str, dict[str, float | str]]:
        """Return serializable phase timing for runs.summary_json."""
        self.end()
        merged = dict(self._phases)
        for name, seconds in self._accumulated.items():
            if name in merged:
                merged[name] = {
                    **merged[name],
                    "seconds": round(float(merged[name]["seconds"]) + seconds, 3),
                }
            else:
                merged[name] = {
                    "start": None,
                    "end": None,
                    "seconds": round(seconds, 3),
                }
        return merged

    def _record_phase(
        self,
        name: str,
        started_at: datetime,
        finished_at: datetime,
        elapsed: float,
    ) -> None:
        self._phases[name] = {
            "start": started_at.isoformat(),
            "end": finished_at.isoformat(),
            "seconds": round(elapsed, 3),
        }
