"""Research executor — cache, budget, provider router, SEC, logging."""

import json
import time
from datetime import datetime, timezone
from typing import Any

from src.agents.research.budget import ResearchBudget
from src.agents.research.cache import ResearchCache
from src.agents.research.providers.router import ProviderRouter
from src.agents.research.sec_search import sec_search
from src.agents.research.types import SECResult, SearchResult
from src.data.database import get_session
from src.data.models import ResearchLog
from src.utils.chat_cost_context import current_chat_cost_context
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("research.executor")


class ResearchExecutor:
    """Executes research tool calls with cache, budget, and logging."""

    def __init__(
        self,
        cycle_id: str,
        cache: ResearchCache | None = None,
        budget: ResearchBudget | None = None,
    ) -> None:
        self._cycle_id = cycle_id
        self._cache = cache or ResearchCache()
        self._budget = budget or ResearchBudget(cycle_id)
        self._router = ProviderRouter()

    def _can_research(self, member: str) -> bool:
        if not get_settings().research_enabled:
            return False
        return self._budget.can_afford(member)

    def web_search(
        self,
        member: str,
        ticker: str,
        query: str,
        num_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Execute web search. Returns list of {url, title, snippet}."""
        if not self._can_research(member):
            return []
        cached = self._cache.get(ticker, "web_search", query)
        if cached is not None:
            self._log(member, ticker, "web_search", query, cached, "brave", cache_hit=True)
            return cached
        t0 = time.perf_counter()
        results, provider = self._router.search(query=query, num_results=num_results)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        serial = [{"url": r.url, "title": r.title, "snippet": r.snippet} for r in results]
        self._budget.record_call(member)
        self._cache.set(ticker, "web_search", query, serial)
        self._log(member, ticker, "web_search", query, serial, provider, cache_hit=False, latency_ms=latency_ms)
        return serial

    def news_search(
        self,
        member: str,
        ticker: str,
        query: str,
        num_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Execute news search with topic: finance."""
        if not self._can_research(member):
            return []
        cached = self._cache.get(ticker, "news_search", query)
        if cached is not None:
            self._log(member, ticker, "news_search", query, cached, "brave", cache_hit=True)
            return cached
        t0 = time.perf_counter()
        results, provider = self._router.search(
            query=query, num_results=num_results, topic="finance"
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        serial = [{"url": r.url, "title": r.title, "snippet": r.snippet} for r in results]
        self._budget.record_call(member)
        self._cache.set(ticker, "news_search", query, serial)
        self._log(member, ticker, "news_search", query, serial, provider, cache_hit=False, latency_ms=latency_ms)
        return serial

    def sector_search(
        self,
        member: str,
        ticker: str,
        sector: str,
        query: str,
        num_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Execute sector/industry search."""
        if not self._can_research(member):
            return []
        full_query = f"{sector} {query}".strip()
        cached = self._cache.get(ticker, "sector_search", full_query)
        if cached is not None:
            self._log(member, ticker, "sector_search", full_query, cached, "brave", cache_hit=True)
            return cached
        t0 = time.perf_counter()
        results, provider = self._router.search(
            query=full_query, num_results=num_results, topic="finance"
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        serial = [{"url": r.url, "title": r.title, "snippet": r.snippet} for r in results]
        self._budget.record_call(member)
        self._cache.set(ticker, "sector_search", full_query, serial)
        self._log(member, ticker, "sector_search", full_query, serial, provider, cache_hit=False, latency_ms=latency_ms)
        return serial

    def sec_search_tool(
        self,
        member: str,
        ticker: str,
        doc_type: str = "10-K",
        num_results: int = 3,
    ) -> list[dict[str, Any]]:
        """Execute SEC EDGAR search. No budget (free) but still log."""
        if not get_settings().research_enabled:
            return []
        cached = self._cache.get(ticker, "sec_search", doc_type)
        if cached is not None:
            self._log(member, ticker, "sec_search", doc_type, cached, "sec", cache_hit=True)
            return cached
        t0 = time.perf_counter()
        results: list[SECResult] = sec_search(ticker, doc_type=doc_type, num_results=num_results)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        serial = [
            {
                "filing_type": r.filing_type,
                "description": r.description,
                "filing_date": r.filing_date,
                "accession_number": r.accession_number,
                "url": r.url,
            }
            for r in results
        ]
        self._cache.set(ticker, "sec_search", doc_type, serial)
        self._log(member, ticker, "sec_search", doc_type, serial, "sec", cache_hit=False, latency_ms=latency_ms)
        return serial

    def macro_search(
        self,
        member: str,
        query: str,
        num_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Search macro/economic topics (Fed policy, rates, GDP, inflation)."""
        if not self._can_research(member):
            return []
        cached = self._cache.get("_MACRO_", "macro_search", query)
        if cached is not None:
            self._log(member, "_MACRO_", "macro_search", query, cached, "brave", cache_hit=True)
            return cached
        t0 = time.perf_counter()
        results, provider = self._router.search(query=query, num_results=num_results, topic="finance")
        latency_ms = int((time.perf_counter() - t0) * 1000)
        serial = [{"url": r.url, "title": r.title, "snippet": r.snippet} for r in results]
        self._budget.record_call(member)
        self._cache.set("_MACRO_", "macro_search", query, serial)
        self._log(member, "_MACRO_", "macro_search", query, serial, provider, cache_hit=False, latency_ms=latency_ms)
        return serial

    def _log(
        self,
        member: str,
        ticker: str,
        tool: str,
        query: str,
        results: list[Any],
        provider: str,
        cache_hit: bool,
        latency_ms: int = 0,
    ) -> None:
        """Persist to ResearchLog and emit EventsLog for dashboard."""
        chat_session_id, chat_turn_id = current_chat_cost_context()
        session = get_session()
        try:
            session.add(
                ResearchLog(
                    cycle_id=self._cycle_id,
                    chat_session_id=chat_session_id,
                    chat_turn_id=chat_turn_id,
                    member=member,
                    ticker=ticker,
                    tool_name=tool,
                    query=query[:500] if query else None,
                    num_results=len(results),
                    results_json=json.dumps(results)[:10000] if results else None,
                    provider=provider,
                    cost_usd=0.005 if not cache_hit and provider in ("brave", "tavily") else 0.0,
                    latency_ms=latency_ms,
                    cache_hit=cache_hit,
                    error=None,
                )
            )
            session.commit()
        except Exception as e:
            logger.debug(f"ResearchLog write failed: {e}")
            session.rollback()
        finally:
            session.close()

        # Emit EventsLog for dashboard SSE (fail-open)
        try:
            from dashboard.backend.app.services.event_logger import log_event
            log_event(
                event_type="research_call",
                source="research",
                message=f"{member} {tool} {ticker or 'general'} ({'cache' if cache_hit else provider})",
                metadata={"member": member, "ticker": ticker, "tool": tool, "cache_hit": cache_hit, "cycle_id": self._cycle_id},
            )
        except ImportError:
            pass
