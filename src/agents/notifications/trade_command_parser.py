"""Natural language trade command parser for Slack inbound messages.

Supports four Slack command modes:
- review: strategy-only analysis
- strategy trade: run strategy, then execute BUY/SELL
- direct trade: BUY/SELL without strategy
- cancel: cancel pending broker orders without strategy
"""

import json
import re
from dataclasses import asdict, dataclass, field

from src.utils.logger import get_logger

logger = get_logger("trade_command_parser")

_TRIGGER_STRATEGY_SUFFIX_RE = re.compile(r"\s+and\s+trigger\s+strategy\s*$", re.IGNORECASE)
_REVIEW_AND_TRADE_RE = re.compile(
    r"^\s*review\s+(?P<subject>.+?)\s+and\s+(?P<action>buy|sell)\s*$",
    re.IGNORECASE,
)
_CANCEL_RE = re.compile(
    r"^\s*cancel\s+(?P<order_class>stop\s+sell|sell|buy)\s+(?P<subjects>.+?)\s*$",
    re.IGNORECASE,
)
_CANCEL_SUBJECT_FIRST_RE = re.compile(
    r"^\s*cancel\s+(?P<subjects>.+?)\s+(?P<order_class>stop\s+sell|sell|buy|orders?|order)\s*$",
    re.IGNORECASE,
)
_REVIEW_RE = re.compile(r"^\s*review\s+(?P<subject>.+?)\s*$", re.IGNORECASE)
_TRADE_RE = re.compile(r"^\s*(?P<action>buy|sell)\s+(?P<body>.+?)\s*$", re.IGNORECASE)
_LEADING_QTY_RE = re.compile(
    r"^(?P<qty>\d+(?:\.\d+)?)\s+(?:shares?\s+(?:of\s+)?)?(?P<subject>.+?)$",
    re.IGNORECASE,
)
_LEADING_AMT_RE = re.compile(
    r"^[£$](?P<amt>\d+(?:\.\d+)?)\s+(?:of\s+|worth\s+(?:of\s+)?)?(?P<subject>.+?)$",
    re.IGNORECASE,
)
_TRAILING_QTY_RE = re.compile(r"^(?P<subject>.+?)\s+(?P<qty>\d+(?:\.\d+)?)$", re.IGNORECASE)
_TRAILING_AMT_RE = re.compile(r"^(?P<subject>.+?)\s+[£$](?P<amt>\d+(?:\.\d+)?)$", re.IGNORECASE)


@dataclass(slots=True)
class TradeCommandIntent:
    """Parsed intent from a natural language trade command."""

    action: str  # BUY, SELL, REVIEW, CANCEL
    ticker: str  # First subject phrase upper-cased for backward compatibility
    quantity_shares: float | None = None
    amount_gbp: float | None = None
    raw_message: str = ""
    force: bool = False  # When True, bypass risk VETO
    command_kind: str = "trade"  # trade, review, cancel
    execution_mode: str = "strategy"  # direct, strategy, cancel_only
    trigger_strategy: bool = False
    cancel_order_class: str | None = None  # buy, sell, stop_sell
    subject_phrases: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self))


# Regex to detect force prefix: "force ", "override ", or leading "!"
_FORCE_PREFIX_RE = re.compile(r"^\s*(?:force\s+|override\s+|!)", re.IGNORECASE)


def _strip_force_prefix(message: str) -> tuple[str, bool]:
    """Strip force/override/! prefix from message. Returns (cleaned_message, is_force)."""
    m = _FORCE_PREFIX_RE.match(message)
    if m:
        return message[m.end():], True
    return message, False


def _normalize_subject(subject: str) -> str:
    return " ".join(subject.split()).strip()


def _split_subjects(text: str) -> list[str]:
    """Split comma-separated ticker/company phrases, allowing a final 'and'."""
    cleaned = _normalize_subject(text)
    if not cleaned:
        return []

    parts = [part.strip() for part in cleaned.split(",") if part.strip()]
    if not parts:
        return []
    if len(parts) == 1:
        return [parts[0]]

    last = parts.pop()
    if " and " in last.lower():
        split_idx = last.lower().rfind(" and ")
        head = last[:split_idx].strip()
        tail = last[split_idx + 5:].strip()
        if head:
            parts.append(head)
        if tail:
            parts.append(tail)
        return parts
    parts.append(last)
    return parts


def _make_intent(
    *,
    action: str,
    raw_message: str,
    force: bool,
    subject_phrases: list[str],
    quantity_shares: float | None = None,
    amount_gbp: float | None = None,
    command_kind: str = "trade",
    execution_mode: str = "direct",
    trigger_strategy: bool = False,
    cancel_order_class: str | None = None,
) -> TradeCommandIntent:
    primary = subject_phrases[0] if subject_phrases else ""
    return TradeCommandIntent(
        action=action,
        ticker=primary.upper(),
        quantity_shares=quantity_shares,
        amount_gbp=amount_gbp,
        raw_message=raw_message,
        force=force,
        command_kind=command_kind,
        execution_mode=execution_mode,
        trigger_strategy=trigger_strategy,
        cancel_order_class=cancel_order_class,
        subject_phrases=subject_phrases,
    )


def _parse_trade_body(body: str) -> tuple[list[str], float | None, float | None] | None:
    cleaned = _normalize_subject(body)
    if not cleaned:
        return None

    for pattern, key in (
        (_LEADING_QTY_RE, "qty"),
        (_LEADING_AMT_RE, "amt"),
        (_TRAILING_QTY_RE, "qty"),
        (_TRAILING_AMT_RE, "amt"),
    ):
        match = pattern.match(cleaned)
        if not match:
            continue
        subject = _normalize_subject(match.group("subject"))
        if not subject:
            return None
        if key == "qty":
            return [subject], float(match.group("qty")), None
        return [subject], None, float(match.group("amt"))

    return [cleaned], None, None


def _try_regex(message: str) -> TradeCommandIntent | None:
    """Attempt to parse via regex patterns (zero-cost path)."""
    cleaned, is_force = _strip_force_prefix(message)
    stripped = cleaned.strip()

    review_and_trade = _REVIEW_AND_TRADE_RE.match(stripped)
    if review_and_trade:
        subject = _normalize_subject(review_and_trade.group("subject"))
        action = review_and_trade.group("action").upper()
        return _make_intent(
            action=action,
            raw_message=message,
            force=is_force,
            subject_phrases=[subject],
            command_kind="trade",
            execution_mode="strategy",
            trigger_strategy=True,
        )

    cancel_match = _CANCEL_RE.match(stripped)
    if cancel_match:
        raw_subjects = _split_subjects(cancel_match.group("subjects"))
        if not raw_subjects:
            return None
        order_class = cancel_match.group("order_class").strip().lower().replace(" ", "_")
        if order_class in {"order", "orders"}:
            order_class = "any"
        return _make_intent(
            action="CANCEL",
            raw_message=message,
            force=is_force,
            subject_phrases=raw_subjects,
            command_kind="cancel",
            execution_mode="cancel_only",
            cancel_order_class=order_class,
        )

    cancel_subject_first_match = _CANCEL_SUBJECT_FIRST_RE.match(stripped)
    if cancel_subject_first_match:
        raw_subjects = _split_subjects(cancel_subject_first_match.group("subjects"))
        if not raw_subjects:
            return None
        order_class = cancel_subject_first_match.group("order_class").strip().lower().replace(" ", "_")
        if order_class in {"order", "orders"}:
            order_class = "any"
        return _make_intent(
            action="CANCEL",
            raw_message=message,
            force=is_force,
            subject_phrases=raw_subjects,
            command_kind="cancel",
            execution_mode="cancel_only",
            cancel_order_class=order_class,
        )

    trigger_strategy = False
    trigger_match = _TRIGGER_STRATEGY_SUFFIX_RE.search(stripped)
    if trigger_match:
        trigger_strategy = True
        stripped = stripped[:trigger_match.start()].strip()

    review_match = _REVIEW_RE.match(stripped)
    if review_match:
        subject = _normalize_subject(review_match.group("subject"))
        return _make_intent(
            action="REVIEW",
            raw_message=message,
            force=is_force,
            subject_phrases=[subject],
            command_kind="review",
            execution_mode="strategy",
            trigger_strategy=trigger_strategy,
        )

    trade_match = _TRADE_RE.match(stripped)
    if trade_match:
        action = trade_match.group("action").upper()
        parsed = _parse_trade_body(trade_match.group("body"))
        if parsed is None:
            return None
        subject_phrases, qty, amt = parsed
        return _make_intent(
            action=action,
            raw_message=message,
            force=is_force,
            subject_phrases=subject_phrases,
            quantity_shares=qty,
            amount_gbp=amt,
            command_kind="trade",
            execution_mode="strategy" if trigger_strategy else "direct",
            trigger_strategy=trigger_strategy,
        )
    return None


def _try_claude(message: str) -> TradeCommandIntent | None:
    """Fall back to Claude for ambiguous NL parsing."""
    try:
        from anthropic import Anthropic

        from src.utils.config import get_settings

        # Detect force prefix before sending to Claude
        cleaned, is_force = _strip_force_prefix(message)

        settings = get_settings()
        client = Anthropic(api_key=settings.anthropic_api_key)

        prompt = (
            "Extract a Slack trading command from this message.\n"
            "Return JSON with exactly these fields:\n"
            '{'
            '"command_kind":"trade"|"review"|"cancel",'
            '"execution_mode":"direct"|"strategy"|"cancel_only",'
            '"trade_action":"BUY"|"SELL"|"REVIEW"|"CANCEL",'
            '"trigger_strategy":true|false,'
            '"cancel_order_class":"buy"|"sell"|"stop_sell"|"any"|null,'
            '"subject_phrases":["<ticker or company phrase>"],'
            '"quantity_shares":<number|null>,'
            '"amount_gbp":<number|null>'
            '}\n'
            "Rules:\n"
            "- Plain buy/sell => direct mode.\n"
            "- 'review X' => review + strategy mode.\n"
            "- 'review X and buy/sell' or 'buy/sell X and trigger strategy' => trade + strategy mode.\n"
            "- 'cancel buy/sell/stop sell X[, Y]', 'cancel X buy', or 'cancel X order' => cancel mode.\n"
            "- If not a trade command, return null.\n\n"
            f"Message: {cleaned}"
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
        action = data.get("trade_action", "").upper()
        if action not in ("BUY", "SELL", "REVIEW", "CANCEL"):
            return None
        command_kind = data.get("command_kind", "").lower()
        execution_mode = data.get("execution_mode", "").lower()
        subject_phrases = [
            _normalize_subject(str(item))
            for item in (data.get("subject_phrases") or [])
            if _normalize_subject(str(item))
        ]
        if command_kind not in ("trade", "review", "cancel"):
            return None
        if execution_mode not in ("direct", "strategy", "cancel_only"):
            return None
        if not subject_phrases and action != "CANCEL":
            return None
        if action == "CANCEL" and not subject_phrases:
            return None
        cancel_order_class = data.get("cancel_order_class")
        if cancel_order_class is not None:
            cancel_order_class = str(cancel_order_class).lower()
            if cancel_order_class not in ("buy", "sell", "stop_sell", "any"):
                return None

        return TradeCommandIntent(
            action=action,
            ticker=(subject_phrases[0].upper() if subject_phrases else ""),
            quantity_shares=data.get("quantity_shares"),
            amount_gbp=data.get("amount_gbp"),
            raw_message=message,
            force=is_force,
            command_kind=command_kind,
            execution_mode=execution_mode,
            trigger_strategy=bool(data.get("trigger_strategy")),
            cancel_order_class=cancel_order_class,
            subject_phrases=subject_phrases,
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
        force_tag = " [FORCE]" if result.force else ""
        logger.info(
            "Parsed trade command via regex: %s %s mode=%s kind=%s%s",
            result.action,
            result.ticker,
            result.execution_mode,
            result.command_kind,
            force_tag,
        )
        return result

    # Fall back to Claude for ambiguous NL
    if use_llm_fallback:
        result = _try_claude(message)
        if result:
            force_tag = " [FORCE]" if result.force else ""
            logger.info(
                "Parsed trade command via Claude: %s %s mode=%s kind=%s%s",
                result.action,
                result.ticker,
                result.execution_mode,
                result.command_kind,
                force_tag,
            )
            return result

    return None
