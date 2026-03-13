"""Base protocol and types for search providers."""

from typing import Protocol, runtime_checkable

from src.agents.research.types import SearchResult


@runtime_checkable
class SearchProviderProtocol(Protocol):
    """Protocol for search providers (Brave, Tavily)."""

    def search(
        self,
        query: str,
        num_results: int = 5,
        topic: str | None = None,
    ) -> list[SearchResult]:
        """Execute search and return normalised results.

        Args:
            query: Search query string.
            num_results: Max number of results to return.
            topic: Optional topic filter (e.g. "finance" for Tavily).

        Returns:
            List of SearchResult; empty on failure.
        """
        ...
