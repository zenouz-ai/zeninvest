"""Tavily Search API client for research layer."""

import time
from urllib.parse import urlparse

import httpx

from src.agents.research.types import SearchResult
from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.search_api_tracker import (
    SERVICE_TAVILY,
    check_search_api_budget,
    log_search_api_call,
)

logger = get_logger("research.tavily")


class TavilySearchProvider:
    """Tavily Search API provider."""

    def __init__(self) -> None:
        self._key = get_settings().get_env_optional("TAVILY_API_KEY")
        self._url = "https://api.tavily.com/search"
        self._timeout = 30

    def search(
        self,
        query: str,
        num_results: int = 5,
        topic: str | None = None,
    ) -> list[SearchResult]:
        """Execute Tavily search. Uses topic filter when provided (e.g. finance)."""
        if not self._key:
            logger.debug("Tavily Search: no API key configured")
            return []
        if not check_search_api_budget(SERVICE_TAVILY):
            logger.debug("Tavily Search: monthly budget exceeded")
            return []

        body = {
            "query": query,
            "search_depth": "basic",
            "max_results": min(num_results, 10),
        }
        if topic:
            body["topic"] = topic
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._key.strip()}",
        }
        t0 = time.perf_counter()
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(self._url, json=body, headers=headers)
            duration_ms = (time.perf_counter() - t0) * 1000
            log_search_api_call(
                service=SERVICE_TAVILY,
                endpoint="/search",
                status_code=resp.status_code,
                duration_ms=duration_ms,
                method="POST",
            )
            if resp.status_code != 200:
                logger.debug(f"Tavily Search failed: {resp.status_code}")
                return []
            data = resp.json()
            results = data.get("results", [])[:num_results]
            out: list[SearchResult] = []
            for r in results:
                content = r.get("content", "") or r.get("description", "") or r.get("title", "")
                url_str = r.get("url", "") or ""
                out.append(
                    SearchResult(
                        url=url_str,
                        title=r.get("title", "") or "",
                        snippet=content,
                        domain=urlparse(url_str).netloc or None,
                    )
                )
            return out
        except Exception as e:
            duration_ms = (time.perf_counter() - t0) * 1000
            log_search_api_call(
                service=SERVICE_TAVILY,
                endpoint="/search",
                status_code=0,
                duration_ms=duration_ms,
                method="POST",
                error=str(e),
            )
            logger.debug(f"Tavily Search error: {e}")
            return []
