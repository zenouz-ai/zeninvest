"""Natural language trade command parser for Slack inbound messages.

Extracts structured trade intent (BUY/SELL/REVIEW + ticker) from freeform text.
Uses regex first (zero cost); falls back to Claude for ambiguous messages.
"""

import json
import re
from dataclasses import asdict, dataclass

from src.utils.logger import get_logger

logger = get_logger("trade_command_parser")

# Regex patterns for common trade command formats
# Matches: BUY AAPL, SELL 10 TSLA, REVIEW MSFT, BUY £500 NVDA, buy 5 shares of AAPL
_ACTION_RE = r"(?P<action>BUY|SELL|REVIEW)"
_QTY_RE = r"(?:(?P<qty>\d+(?:\.\d+)?)\s+(?:shares?\s+(?:of\s+)?)?)"
_AMT_RE = r"(?:[£$](?P<amt>\d+(?:\.\d+)?)\s+(?:of\s+|worth\s+(?:of\s+)?)?)"
_TICKER_RE = r"(?P<ticker>[A-Z]{1,5}(?:\.[A-Z])?)"

_PATTERNS = [
    # "BUY 10 shares of AAPL" or "BUY 10 AAPL"
    re.compile(rf"^\s*{_ACTION_RE}\s+{_QTY_RE}{_TICKER_RE}\s*$", re.IGNORECASE),
    # "BUY £500 AAPL" or "BUY $500 of AAPL"
    re.compile(rf"^\s*{_ACTION_RE}\s+{_AMT_RE}{_TICKER_RE}\s*$", re.IGNORECASE),
    # "BUY AAPL" (simplest)
    re.compile(rf"^\s*{_ACTION_RE}\s+{_TICKER_RE}\s*$", re.IGNORECASE),
    # "BUY AAPL 10" (ticker before qty)
    re.compile(
        rf"^\s*{_ACTION_RE}\s+{_TICKER_RE}\s+(?P<qty>\d+(?:\.\d+)?)\s*$",
        re.IGNORECASE,
    ),
    # "BUY AAPL £500" (ticker before amount)
    re.compile(
        rf"^\s*{_ACTION_RE}\s+{_TICKER_RE}\s+[£$](?P<amt>\d+(?:\.\d+)?)\s*$",
        re.IGNORECASE,
    ),
]


@dataclass(slots=True)
class TradeCommandIntent:
    """Parsed intent from a natural language trade command."""

    action: str  # BUY, SELL, REVIEW
    ticker: str  # Plain symbol as extracted (e.g. "AAPL")
    quantity_shares: float | None = None
    amount_gbp: float | None = None
    raw_message: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def _try_regex(message: str) -> TradeCommandIntent | None:
    """Attempt to parse via regex patterns (zero-cost path)."""
    for pattern in _PATTERNS:
        m = pattern.match(message.strip())
        if m:
            groups = m.groupdict()
            action = groups["action"].upper()
            ticker = groups["ticker"].upper()
            qty = float(groups["qty"]) if groups.get("qty") else None
            amt = float(groups["amt"]) if groups.get("amt") else None
            return TradeCommandIntent(
                action=action,
                ticker=ticker,
                quantity_shares=qty,
                amount_gbp=amt,
                raw_message=message,
            )
    return None


def _try_claude(message: str) -> TradeCommandIntent | None:
    """Fall back to Claude for ambiguous NL parsing."""
    try:
        from anthropic import Anthropic

        from src.utils.config import get_settings

        settings = get_settings()
        client = Anthropic(api_key=settings.anthropic_api_key)

        prompt = (
            "Extract a trade command from this message. Return JSON with exactly these fields:\n"
            '{"action": "BUY"|"SELL"|"REVIEW", "ticker": "<SYMBOL>", '
            '"quantity_shares": <number|null>, "amount_gbp": <number|null>}\n'
            "If the message is not a trade command, return null.\n\n"
            f"Message: {message}"
        )

        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()

        if text.lower() == "null" or not text:
            return None

        # Extract JSON from response (may be wrapped in markdown)
        json_match = re.search(r"\{[^}]+\}", text)
        if not json_match:
            return None

        data = json.loads(json_match.group())
        action = data.get("action", "").upper()
        if action not in ("BUY", "SELL", "REVIEW"):
            return None
        ticker = data.get("ticker", "").upper()
        if not ticker:
            return None

        return TradeCommandIntent(
            action=action,
            ticker=ticker,
            quantity_shares=data.get("quantity_shares"),
            amount_gbp=data.get("amount_gbp"),
            raw_message=message,
        )
    except Exception as e:
        logger.warning(f"Claude NL parse failed: {e}")
        return None


def parse_trade_command(message: str, use_llm_fallback: bool = True) -> TradeCommandIntent | None:
    """Parse a natural language trade command into structured intent.

    Uses regex first (zero cost). Falls back to Claude for ambiguous messages.

    Args:
        message: Raw user message text.
        use_llm_fallback: Whether to use Claude if regex fails. Default True.

    Returns:
        TradeCommandIntent if parseable, None otherwise.
    """
    if not message or not message.strip():
        return None

    # Try regex first (covers >90% of expected inputs)
    result = _try_regex(message)
    if result:
        logger.info(f"Parsed trade command via regex: {result.action} {result.ticker}")
        return result

    # Fall back to Claude for ambiguous NL
    if use_llm_fallback:
        result = _try_claude(message)
        if result:
            logger.info(f"Parsed trade command via Claude: {result.action} {result.ticker}")
            return result

    return None
