"""Shared types for the research layer."""

from dataclasses import dataclass


@dataclass
class SearchResult:
    """Normalised web search result."""

    url: str
    title: str
    snippet: str
    domain: str | None = None


@dataclass
class SECResult:
    """SEC filing search result."""

    filing_type: str
    description: str | None
    filing_date: str
    accession_number: str
    url: str
