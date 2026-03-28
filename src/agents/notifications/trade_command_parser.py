"""Natural language trade command parser for Slack inbound messages.

Supports four Slack command modes:
- review: strategy-only analysis
- strategy trade: run strategy, then execute BUY/SELL
- direct trade: BUY/SELL without strategy
- cancel: cancel pending broker orders without strategy
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from dataclasses import asdict, dataclass, field

from src.data.database import get_session
from src.data.models import IntentDetectionCache
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
_CANCEL_ANY_RE = re.compile(r"^\s*cancel\s+(?P<subjects>.+?)\s*$", re.IGNORECASE)
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
_LEADING_FORMATTING_RE = re.compile(r"^(?:<@[^>]+>\s*|[\-\*\u2022]+\s*|\d+[.)]\s*)+", re.IGNORECASE)
_LEADING_GREETING_RE = re.compile(r"^(?:hi|hello|hey|yo|ok|okay|please)\b[\s,!:;\-]+", re.IGNORECASE)
_EMPHASIZED_COMMAND_RE = re.compile(r"^\*(buy|sell|review|cancel)\*\s+", re.IGNORECASE)


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


def _normalize_message(message: str) -> str:
    """Remove harmless decoration that should not block command parsing."""
    if not message:
        return ""

    text = (
        str(message)
        .replace("\u00a0", " ")
        .replace("\u200b", "")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    text = " ".join(text.split())

    while text:
        updated = _LEADING_FORMATTING_RE.sub("", text).strip()
        updated = _EMPHASIZED_COMMAND_RE.sub(r"\1 ", updated).strip()
        updated = _LEADING_GREETING_RE.sub("", updated).strip()
        if updated == text:
            break
        text = updated

    return text


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _cache_identity(message: str) -> str:
    normalized_message = _normalize_message(message)
    cleaned, _ = _strip_force_prefix(normalized_message)
    return cleaned.strip().lower()


def _cache_key(message: str) -> str | None:
    canonical = _cache_identity(message)
    if not canonical:
        return None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def _intent_to_cache_payload(intent: TradeCommandIntent) -> dict[str, object]:
    payload = asdict(intent)
    payload.pop("raw_message", None)
    payload.pop("force", None)
    return payload


def _intent_from_payload(payload: dict[str, object], *, raw_message: str, force: bool) -> TradeCommandIntent | None:
    action = str(payload.get("action", "")).upper()
    if action not in ("BUY", "SELL", "REVIEW", "CANCEL"):
        return None

    command_kind = str(payload.get("command_kind", "")).lower()
    execution_mode = str(payload.get("execution_mode", "")).lower()
    if command_kind not in ("trade", "review", "cancel"):
        return None
    if execution_mode not in ("direct", "strategy", "cancel_only"):
        return None

    subject_phrases = [
        _normalize_subject(str(item))
        for item in (payload.get("subject_phrases") or [])
        if _normalize_subject(str(item))
    ]
    if not subject_phrases:
        return None

    cancel_order_class = payload.get("cancel_order_class")
    if cancel_order_class is not None:
        cancel_order_class = str(cancel_order_class).lower()
        if cancel_order_class not in ("buy", "sell", "stop_sell", "any"):
            return None

    try:
        quantity_shares = float(payload["quantity_shares"]) if payload.get("quantity_shares") is not None else None
        amount_gbp = float(payload["amount_gbp"]) if payload.get("amount_gbp") is not None else None
    except (TypeError, ValueError):
        return None

    return TradeCommandIntent(
        action=action,
        ticker=(subject_phrases[0].upper() if subject_phrases else ""),
        quantity_shares=quantity_shares,
        amount_gbp=amount_gbp,
        raw_message=raw_message,
        force=force,
        command_kind=command_kind,
        execution_mode=execution_mode,
        trigger_strategy=bool(payload.get("trigger_strategy")),
        cancel_order_class=cancel_order_class,
        subject_phrases=subject_phrases,
    )


def _load_cached_intent(message: str) -> TradeCommandIntent | None:
    key = _cache_key(message)
    if key is None:
        return None

    normalized_message = _normalize_message(message)
    _, is_force = _strip_force_prefix(normalized_message)
    session = get_session()
    try:
        row = session.query(IntentDetectionCache).filter(IntentDetectionCache.cache_key == key).first()
        if row is None:
            return None
        payload = json.loads(row.intent_json)
        intent = _intent_from_payload(payload, raw_message=message, force=is_force)
        if intent is None:
            logger.warning("Intent cache payload invalid for key=%s", key)
            return None
        row.hit_count = int(row.hit_count or 0) + 1
        row.last_used_at = _utcnow()
        session.commit()
        logger.info(
            "Parsed trade command via cache: %s %s mode=%s kind=%s",
            intent.action,
            intent.ticker,
            intent.execution_mode,
            intent.command_kind,
        )
        return intent
    except Exception as exc:
        session.rollback()
        logger.warning("Intent cache lookup failed: %s", exc)
        return None
    finally:
        session.close()


def _store_cached_intent(message: str, intent: TradeCommandIntent, *, source: str = "claude") -> None:
    key = _cache_key(message)
    canonical = _cache_identity(message)
    if key is None or not canonical:
        return

    session = get_session()
    try:
        row = session.query(IntentDetectionCache).filter(IntentDetectionCache.cache_key == key).first()
        payload_json = json.dumps(_intent_to_cache_payload(intent))
        now = _utcnow()
        if row is None:
            row = IntentDetectionCache(
                cache_key=key,
                normalized_message=canonical,
                example_message=message,
                source=source,
                intent_kind=intent.command_kind,
                intent_json=payload_json,
                hit_count=1,
                created_at=now,
                last_used_at=now,
            )
            session.add(row)
        else:
            row.normalized_message = canonical
            row.example_message = message
            row.source = source
            row.intent_kind = intent.command_kind
            row.intent_json = payload_json
            row.last_used_at = now
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.warning("Intent cache write failed: %s", exc)
    finally:
        session.close()


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
    normalized_message = _normalize_message(message)
    cleaned, is_force = _strip_force_prefix(normalized_message)
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

    cancel_any_match = _CANCEL_ANY_RE.match(stripped)
    if cancel_any_match:
        raw_subjects = _split_subjects(cancel_any_match.group("subjects"))
        if not raw_subjects:
            return None
        lower_subjects = {subject.lower() for subject in raw_subjects}
        if lower_subjects <= {"buy", "sell", "stop sell", "stop_sell", "order", "orders"}:
            return None
        return _make_intent(
            action="CANCEL",
            raw_message=message,
            force=is_force,
            subject_phrases=raw_subjects,
            command_kind="cancel",
            execution_mode="cancel_only",
            cancel_order_class="any",
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
        payload = {
            "action": data.get("trade_action"),
            "command_kind": data.get("command_kind"),
            "execution_mode": data.get("execution_mode"),
            "trigger_strategy": data.get("trigger_strategy"),
            "cancel_order_class": data.get("cancel_order_class"),
            "subject_phrases": data.get("subject_phrases"),
            "quantity_shares": data.get("quantity_shares"),
            "amount_gbp": data.get("amount_gbp"),
        }
        return _intent_from_payload(payload, raw_message=message, force=is_force)
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

    if use_llm_fallback:
        result = _load_cached_intent(message)
        if result:
            return result

    # Fall back to Claude for ambiguous NL
    if use_llm_fallback:
        result = _try_claude(message)
        if result:
            _store_cached_intent(message, result, source="claude")
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
