"""Ticker format conversion between Trading 212 and yfinance."""

# See CLAUDE.md Ticker Format Gotcha for rationale.

import re

from src.data.database import get_session
from src.data.models import Instrument
from src.utils.logger import get_logger

logger = get_logger("ticker_utils")


# Trading 212 sometimes keeps legacy internal instrument ids after ticker changes
# (commonly former SPAC identifiers). These overrides map between the internal
# T212 id and the live market symbol used by yfinance and human users.
T212_TO_MARKET_SYMBOL_OVERRIDES = {
    "DMYI_US_EQ": "IONQ",
    "VACQ_US_EQ": "RKLB",
}
MARKET_SYMBOL_TO_T212_OVERRIDES = {
    market_symbol: t212_symbol
    for t212_symbol, market_symbol in T212_TO_MARKET_SYMBOL_OVERRIDES.items()
}

# Common user-facing company aliases that do not appear verbatim in instrument names.
COMPANY_NAME_ALIASES = {
    "GOOGLE": "GOOGL",
    "GOOGLE CLASS A": "GOOGL",
    "GOOGLE CLASS C": "GOOG",
    "ALPHABET CLASS A": "GOOGL",
    "ALPHABET CLASS C": "GOOG",
    "FACEBOOK": "META",
}

_LEADING_TRAILING_PUNCT_RE = re.compile(r"^[^\w]+|[^\w./-]+$")


def t212_to_yf(ticker: str) -> str:
    """Convert T212 ticker to yfinance symbol.

    Rules:
    - SYMBOL_US_EQ  -> SYMBOL   (e.g. AAPL_US_EQ -> AAPL)
    - SYMBOL_UK_EQ  -> SYMBOL   (e.g. BP._UK_EQ -> BP.)
    - SYMBOL_EQ     -> SYMBOL   (non-standard suffix)
    - TAP/A_US_EQ   -> TAP-A    (Class A: slash -> hyphen)
    - BRK_B_US_EQ   -> BRK.B    (Class B: _X -> .X when X is single letter)

    Args:
        ticker: T212 format (e.g. AAPL_US_EQ, BRK_B_US_EQ, TAP/A_US_EQ)

    Returns:
        yfinance symbol (e.g. AAPL, BRK.B, TAP-A)
    """
    normalized = ticker.strip().upper()
    if normalized in T212_TO_MARKET_SYMBOL_OVERRIDES:
        return T212_TO_MARKET_SYMBOL_OVERRIDES[normalized]

    base = normalized.replace("_US_EQ", "").replace("_UK_EQ", "").strip()
    if base.endswith("_EQ"):
        base = base[:-3].strip()  # Fallback for non-standard suffix (e.g. VPNUS_EQ)
    base = base.replace("/", "-")  # Class A: TAP/A -> TAP-A (Yahoo uses hyphen)
    if "_" in base:
        parts = base.rsplit("_", 1)
        if len(parts) == 2 and len(parts[1]) == 1 and parts[1].isalpha():
            base = f"{parts[0]}.{parts[1]}"  # Class B: BRK_B -> BRK.B
    return base


def resolve_ticker_to_t212(symbol: str) -> str | None:
    """Resolve a plain symbol (e.g. 'AAPL') to T212 ticker (e.g. 'AAPL_US_EQ').

    Lookup order:
    1. Exact match in Instrument table (already T212 format)
    2. Append _US_EQ suffix and check
    3. Case-insensitive search on Instrument.name

    Returns None if not found.
    """
    if not symbol or not symbol.strip():
        return None
    symbol = _LEADING_TRAILING_PUNCT_RE.sub("", symbol.strip()).upper()
    symbol = COMPANY_NAME_ALIASES.get(symbol, symbol)
    if not symbol:
        return None
    session = get_session()
    try:
        # 0. Known alias override (e.g. IONQ -> DMYI_US_EQ, RKLB -> VACQ_US_EQ)
        alias_ticker = MARKET_SYMBOL_TO_T212_OVERRIDES.get(symbol)
        if alias_ticker:
            inst = session.query(Instrument).filter(Instrument.ticker == alias_ticker).first()
            if inst:
                return inst.ticker

        # 1. Exact match (user may have typed the T212 format directly)
        inst = session.query(Instrument).filter(Instrument.ticker == symbol).first()
        if inst:
            return inst.ticker

        # 2. Append _US_EQ (most common case: "AAPL" -> "AAPL_US_EQ")
        t212_candidate = f"{symbol}_US_EQ"
        inst = session.query(Instrument).filter(Instrument.ticker == t212_candidate).first()
        if inst:
            return inst.ticker

        # 3. Case-insensitive name search (e.g. "Apple" -> "AAPL_US_EQ")
        inst = (
            session.query(Instrument)
            .filter(Instrument.name.ilike(f"%{symbol}%"))
            .first()
        )
        if inst:
            return inst.ticker

        return None
    except Exception as e:
        logger.warning(f"Ticker resolution failed for '{symbol}': {e}")
        return None
    finally:
        session.close()
