"""Deterministic entity resolver for conversational trading (US-1.9 Phase 3).

Resolves pronouns, references, and portfolio-scoped expressions to concrete
ticker lists using session context.  No LLM calls — pure rule-based resolution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.agents.conversation.context import SessionContext
from src.utils.logger import get_logger

logger = get_logger("entity_resolver")

# --- Pronoun / reference patterns ---

_IT_RE = re.compile(
    r"\b(it|that\s+stock|that\s+one|this\s+stock|this\s+one|the\s+stock)\b", re.I
)
_BOTH_RE = re.compile(r"\b(both|them|those|these|the\s+two)\b", re.I)
_FIRST_RE = re.compile(r"\b(the\s+first(\s+one)?|first\s+one)\b", re.I)
_SECOND_RE = re.compile(r"\b(the\s+second(\s+one)?|second\s+one)\b", re.I)
_WINNER_RE = re.compile(
    r"\b(the\s+winner|the\s+stronger\s+one|the\s+better\s+one|the\s+best)\b", re.I
)
_LOSER_RE = re.compile(
    r"\b(the\s+loser|the\s+weaker\s+one|the\s+worse\s+one|the\s+worst)\b", re.I
)

# --- Portfolio scope patterns ---

_ALL_SECTOR_RE = re.compile(
    r"\ball\s+(tech|technology|healthcare|finance|financial|energy|consumer|industrial|"
    r"utility|utilities|materials|real\s+estate|communication)\s*(stocks?|positions?|holdings?)?\b",
    re.I,
)
_EVERYTHING_UNDER_RE = re.compile(
    r"\beverything\s+(?:under|below)\s*[£$]?\s*(\d+(?:\.\d+)?)\b", re.I
)

# Sector name normalization for matching against Instrument.sector
_SECTOR_MAP: dict[str, str] = {
    "tech": "Technology",
    "technology": "Technology",
    "healthcare": "Healthcare",
    "finance": "Financial Services",
    "financial": "Financial Services",
    "energy": "Energy",
    "consumer": "Consumer Cyclical",
    "industrial": "Industrials",
    "utility": "Utilities",
    "utilities": "Utilities",
    "materials": "Basic Materials",
    "real estate": "Real Estate",
    "communication": "Communication Services",
}


@dataclass
class ResolvedEntities:
    """Result of entity resolution."""

    tickers: list[str] = field(default_factory=list)
    confidence: float = 0.0
    method: str = "none"  # pronoun, ordinal, winner, portfolio_scope, explicit, none
    needs_confirmation: bool = False  # True when confidence is medium (0.5-0.8)
    confirmation_prompt: str = ""
    audit: dict[str, Any] = field(default_factory=dict)

    @property
    def resolved(self) -> bool:
        """True when resolution produced a usable result (tickers found or
        a confirmation prompt that needs user input)."""
        if self.needs_confirmation and self.confidence > 0.0:
            return True
        return len(self.tickers) > 0 and self.confidence > 0.0


class EntityResolver:
    """Rule-based entity resolver using session context.

    Resolution layers (tried in order):
    1. Explicit tickers in the message (already resolved by caller)
    2. Pronoun / reference resolution ("it", "that stock", "both", etc.)
    3. Ordinal resolution ("the first one", "second one")
    4. Winner/loser from compare result
    5. Portfolio-scoped expressions ("all tech stocks", "everything under £200")
    """

    def resolve(
        self,
        message: str,
        context: SessionContext,
        *,
        explicit_tickers: list[str] | None = None,
    ) -> ResolvedEntities:
        """Resolve entity references in *message* using *context*.

        Parameters
        ----------
        message : str
            The raw user message.
        context : SessionContext
            Current session context with ticker history.
        explicit_tickers : list[str] | None
            Tickers already extracted by the caller (e.g. from regex).
            If provided and non-empty, resolution skips pronoun/reference
            layers and returns these directly.
        """
        if not message:
            return ResolvedEntities()

        # Layer 1: explicit tickers override everything
        if explicit_tickers:
            return ResolvedEntities(
                tickers=explicit_tickers,
                confidence=0.95,
                method="explicit",
                audit={"source": "caller_provided"},
            )

        # Layer 2: pronoun / singular reference
        result = self._resolve_pronoun(message, context)
        if result.resolved:
            return result

        # Layer 3: ordinal ("first one", "second one")
        result = self._resolve_ordinal(message, context)
        if result.resolved:
            return result

        # Layer 4: winner / loser from compare
        result = self._resolve_winner_loser(message, context)
        if result.resolved:
            return result

        # Layer 5: portfolio scope ("all tech stocks", "everything under £200")
        result = self._resolve_portfolio_scope(message, context)
        if result.resolved:
            return result

        return ResolvedEntities(audit={"unresolved": True, "message": message[:100]})

    # ------------------------------------------------------------------
    # Layer 2: pronouns
    # ------------------------------------------------------------------

    def _resolve_pronoun(self, message: str, context: SessionContext) -> ResolvedEntities:
        subjects = context.last_subject_tickers

        if _BOTH_RE.search(message):
            if len(subjects) >= 2:
                return ResolvedEntities(
                    tickers=subjects[:2],
                    confidence=0.85,
                    method="pronoun",
                    audit={"pattern": "both/them", "source_tickers": subjects[:2]},
                )
            return ResolvedEntities(
                confidence=0.3,
                method="pronoun",
                needs_confirmation=True,
                confirmation_prompt="Which tickers are you referring to?",
                audit={"pattern": "both/them", "insufficient_context": True},
            )

        if _IT_RE.search(message):
            if subjects:
                return ResolvedEntities(
                    tickers=[subjects[0]],
                    confidence=0.85,
                    method="pronoun",
                    audit={"pattern": "it/that", "source_ticker": subjects[0]},
                )
            return ResolvedEntities(
                confidence=0.3,
                method="pronoun",
                needs_confirmation=True,
                confirmation_prompt="Which stock are you referring to?",
                audit={"pattern": "it/that", "no_context": True},
            )

        return ResolvedEntities()

    # ------------------------------------------------------------------
    # Layer 3: ordinals
    # ------------------------------------------------------------------

    def _resolve_ordinal(self, message: str, context: SessionContext) -> ResolvedEntities:
        subjects = context.last_subject_tickers or context.last_selection_tickers

        if _FIRST_RE.search(message) and len(subjects) >= 1:
            return ResolvedEntities(
                tickers=[subjects[0]],
                confidence=0.85,
                method="ordinal",
                audit={"pattern": "first", "source_ticker": subjects[0]},
            )

        if _SECOND_RE.search(message) and len(subjects) >= 2:
            return ResolvedEntities(
                tickers=[subjects[1]],
                confidence=0.85,
                method="ordinal",
                audit={"pattern": "second", "source_ticker": subjects[1]},
            )

        return ResolvedEntities()

    # ------------------------------------------------------------------
    # Layer 4: winner / loser from compare
    # ------------------------------------------------------------------

    def _resolve_winner_loser(self, message: str, context: SessionContext) -> ResolvedEntities:
        selection = context.last_selection_result
        if not selection or not isinstance(selection, dict):
            return ResolvedEntities()

        if _WINNER_RE.search(message):
            winner = selection.get("winner")
            if winner:
                return ResolvedEntities(
                    tickers=[winner],
                    confidence=0.90,
                    method="winner",
                    audit={"pattern": "winner", "winner": winner},
                )

        if _LOSER_RE.search(message):
            loser = selection.get("loser")
            if loser:
                return ResolvedEntities(
                    tickers=[loser],
                    confidence=0.90,
                    method="loser",
                    audit={"pattern": "loser", "loser": loser},
                )

        return ResolvedEntities()

    # ------------------------------------------------------------------
    # Layer 5: portfolio scope
    # ------------------------------------------------------------------

    def _resolve_portfolio_scope(self, message: str, context: SessionContext) -> ResolvedEntities:
        # "all tech stocks" → filter active tickers by sector
        m = _ALL_SECTOR_RE.search(message)
        if m:
            sector_key = m.group(1).lower().strip()
            target_sector = _SECTOR_MAP.get(sector_key)
            if target_sector:
                return ResolvedEntities(
                    tickers=[],  # tickers resolved at execution time by querying positions
                    confidence=0.75,
                    method="portfolio_scope",
                    needs_confirmation=True,
                    confirmation_prompt=f"This will target all {target_sector} positions. Proceed?",
                    audit={"pattern": "sector_scope", "sector": target_sector},
                )

        # "everything under £200"
        m = _EVERYTHING_UNDER_RE.search(message)
        if m:
            threshold = float(m.group(1))
            return ResolvedEntities(
                tickers=[],  # resolved at execution time
                confidence=0.75,
                method="portfolio_scope",
                needs_confirmation=True,
                confirmation_prompt=f"This will target all positions valued under £{threshold:.0f}. Proceed?",
                audit={"pattern": "value_below", "threshold": threshold},
            )

        return ResolvedEntities()
