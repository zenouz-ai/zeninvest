"""Research budget — per-member caps (20/8/7) and total per-cycle cap (35)."""

import threading

from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("research.budget")


class ResearchBudget:
    """Tracks per-member and total research calls per cycle.

    Thread-safe: the GPT-4o and Gemini moderators may share one budget across
    threads when moderation runs in parallel (US-9.5).
    """

    def __init__(self, cycle_id: str) -> None:
        self._cycle_id = cycle_id
        self._member_calls: dict[str, int] = {}
        self._total_calls = 0
        self._lock = threading.Lock()
        settings = get_settings()
        self._caps = settings.research_max_calls_per_member_per_cycle
        self._max_total = settings.research_max_total_calls_per_cycle

    def can_afford(self, member: str) -> bool:
        """Return True if member has room and total cap not exceeded."""
        if member not in self._caps:
            logger.warning(f"Unknown research member '{member}', denying")
            return False
        with self._lock:
            member_cap = self._caps[member]
            member_used = self._member_calls.get(member, 0)
            if member_used >= member_cap:
                return False
            if self._total_calls >= self._max_total:
                return False
            return True

    def record_call(self, member: str) -> None:
        """Record one research call for member."""
        with self._lock:
            self._member_calls[member] = self._member_calls.get(member, 0) + 1
            self._total_calls += 1
