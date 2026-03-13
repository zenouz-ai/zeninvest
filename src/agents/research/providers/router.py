"""Provider router — primary (Brave) with Tavily fallback."""

from src.agents.research.providers.base import SearchProviderProtocol
from src.agents.research.providers.brave import BraveSearchProvider
from src.agents.research.providers.tavily import TavilySearchProvider
from src.agents.research.types import SearchResult


class ProviderRouter:
    """Orchestrates search: primary (Brave) then Tavily fallback on failure."""

    def __init__(self) -> None:
        self._primary: SearchProviderProtocol = BraveSearchProvider()
        self._fallback: SearchProviderProtocol = TavilySearchProvider()

    def search(
        self,
        query: str,
        num_results: int = 5,
        topic: str | None = None,
    ) -> tuple[list[SearchResult], str]:
        """Execute search; try primary, fallback on empty or error.

        Returns:
            (results, provider_name) — provider is "brave" or "tavily".
        """
        results = self._primary.search(query=query, num_results=num_results, topic=topic)
        if results:
            return (results, "brave")

        results = self._fallback.search(query=query, num_results=num_results, topic=topic)
        if results:
            return (results, "tavily")

        return ([], "brave")  # Report primary even on total failure
