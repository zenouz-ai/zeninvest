"""Brave Search API client for research layer."""

import time
from urllib.parse import urlparse

import httpx

from src.agents.research.types import SearchResult
from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.search_api_tracker import (
    SERVICE_BRAVE_SEARCH,
    check_search_api_budget,
    log_search_api_call,
)

logger = get_logger("research.brave")


class BraveSearchProvider:
    """Brave Search API provider."""

    def __init__(self) -> None:
        self._key = get_settings().get_env_optional("BRAVE_SEARCH_API_KEY")
        self._url = "https://api.search.brave.com/res/v1/web/search"
        self._timeout = 15

    def search(
        self,
        query: str,
        num_results: int = 5,
        topic: str | None = None,
    ) -> list[SearchResult]:
        """Execute Brave web search. Ignores topic (Brave has no native topic filter)."""
        if not self._key:
            logger.debug("Brave Search: no API key configured")
            return []
        if not check_search_api_budget(SERVICE_BRAVE_SEARCH):
            logger.debug("Brave Search: monthly budget exceeded")
            return []

        params = {"q": query, "count": min(num_results, 20)}
        headers = {"X-Subscription-Token": self._key}
        t0 = time.perf_counter()
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(self._url, params=params, headers=headers)
            duration_ms = (time.perf_counter() - t0) * 1000
            log_search_api_call(
                service=SERVICE_BRAVE_SEARCH,
                endpoint="/res/v1/web/search",
                status_code=resp.status_code,
                duration_ms=duration_ms,
                method="GET",
            )
            if resp.status_code != 200:
                logger.debug(f"Brave Search failed: {resp.status_code}")
                return []
            data = resp.json()
            results = data.get("web", {}).get("results", [])[:num_results]
            return [
                SearchResult(
                    url=r.get("url", "") or "",
                    title=r.get("title", "") or "",
                    snippet=r.get("description", "") or "",
                    domain=urlparse(r.get("url", "") or "").netloc or None,
                )
                for r in results
            ]
        except Exception as e:
            duration_ms = (time.perf_counter() - t0) * 1000
            log_search_api_call(
                service=SERVICE_BRAVE_SEARCH,
                endpoint="/res/v1/web/search",
                status_code=0,
                duration_ms=duration_ms,
                method="GET",
                error=str(e),
            )
            logger.debug(f"Brave Search error: {e}")
            return []
