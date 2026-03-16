"""Ticker format conversion between Trading 212 and yfinance."""

# See CLAUDE.md Ticker Format Gotcha for rationale.


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
    base = ticker.replace("_US_EQ", "").replace("_UK_EQ", "").strip()
    if base.endswith("_EQ"):
        base = base[:-3].strip()  # Fallback for non-standard suffix (e.g. VPNUS_EQ)
    base = base.replace("/", "-")  # Class A: TAP/A -> TAP-A (Yahoo uses hyphen)
    if "_" in base:
        parts = base.rsplit("_", 1)
        if len(parts) == 2 and len(parts[1]) == 1 and parts[1].isalpha():
            base = f"{parts[0]}.{parts[1]}"  # Class B: BRK_B -> BRK.B
    return base
