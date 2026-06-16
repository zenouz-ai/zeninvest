"""Shared exit-reason and 3-class outcome labeling for trades.

Used by the trade-review dashboard and the learning label pipeline so
realized P&L is authoritative when a trade has closed. Stop exits are
split into loss stops vs profit-lock / trailing stops.
"""

from __future__ import annotations

from src.learning.spec import LabelConfig, get_effective_label_config

FLAT_PNL_PCT_THRESHOLD = 0.5

EXIT_REASON_HARD_STOP = "hard_stop"
EXIT_REASON_TRAILING_STOP = "trailing_stop_exit"
EXIT_REASON_STAGNATION = "stagnation_exit"
EXIT_REASON_MANUAL = "manual_or_strategy"

EXIT_LABELS: dict[str, str] = {
    EXIT_REASON_HARD_STOP: "Stop loss exit",
    EXIT_REASON_TRAILING_STOP: "Trailing stop (profit lock)",
    EXIT_REASON_STAGNATION: "Stagnation / stale exit",
    EXIT_REASON_MANUAL: "Market / strategy exit",
}


def infer_exit_reason(
    *,
    sell_timestamp,
    buy_warning_note: str | None,
    stop_adjustments: list[dict],
    pnl_pct: float | None = None,
    sell_order_type: str | None = None,
) -> str:
    """Classify how the position was closed."""
    from src.utils.datetime_utils import ensure_utc_datetime

    if sell_timestamp is None:
        return EXIT_REASON_MANUAL

    sell_utc = ensure_utc_datetime(sell_timestamp)
    if sell_utc is None:
        return EXIT_REASON_MANUAL

    stop_nearby = False
    for adj in stop_adjustments:
        adj_ts = ensure_utc_datetime(adj.get("timestamp"))
        if adj_ts is None:
            continue
        delta = abs((adj_ts - sell_utc).total_seconds())
        if delta <= 3600 and adj.get("status") in {"placed", "filled"}:
            stop_nearby = True
            break

    order_is_stop = (sell_order_type or "").lower() == "stop"
    profitable = pnl_pct is not None and pnl_pct > FLAT_PNL_PCT_THRESHOLD

    if stop_nearby or order_is_stop:
        if profitable:
            return EXIT_REASON_TRAILING_STOP
        return EXIT_REASON_HARD_STOP

    note = buy_warning_note or ""
    if isinstance(note, str) and "stagnation" in note.lower():
        return EXIT_REASON_STAGNATION
    return EXIT_REASON_MANUAL


def _resolve_label_config(label_cfg: LabelConfig | None) -> LabelConfig:
    return label_cfg or get_effective_label_config()


def gain_per_day_pct(pnl_pct: float, holding_days: float | None) -> float:
    """Realized return pace (%/calendar day). Same-day trades use 1 day minimum."""
    holding = max(holding_days or 0.0, 1.0)
    return pnl_pct / holding


def classification_rules_dict(label_cfg: LabelConfig | None = None) -> dict[str, object]:
    """Thresholds and exit codes for dashboard classification reference."""
    cfg = _resolve_label_config(label_cfg)
    return {
        "flat_abs_pnl_pct": FLAT_PNL_PCT_THRESHOLD,
        "success_min_profit_per_day_pct": cfg.success_min_profit_per_day_pct,
        "stall_min_gain_per_day_pct": cfg.stall_min_gain_per_day_pct,
        "exit_reasons": [{"code": code, "label": label} for code, label in EXIT_LABELS.items()],
    }


def is_big_winner(
    pnl_pct: float,
    holding_days: float | None,
    label_cfg: LabelConfig | None = None,
) -> bool:
    """True when gain/day meets the winner threshold."""
    cfg = _resolve_label_config(label_cfg)
    return gain_per_day_pct(pnl_pct, holding_days) >= cfg.success_min_profit_per_day_pct


def is_stall_label(
    pnl_pct: float,
    holding_days: float | None,
    label_cfg: LabelConfig | None = None,
) -> bool:
    """True when gain/day is in the stall band (below winner, at/above stall floor)."""
    cfg = _resolve_label_config(label_cfg)
    gpd = gain_per_day_pct(pnl_pct, holding_days)
    return cfg.stall_min_gain_per_day_pct <= gpd < cfg.success_min_profit_per_day_pct


def is_big_loser(
    pnl_pct: float,
    holding_days: float | None,
    label_cfg: LabelConfig | None = None,
) -> bool:
    """True when gain/day is below the stall floor."""
    cfg = _resolve_label_config(label_cfg)
    return gain_per_day_pct(pnl_pct, holding_days) < cfg.stall_min_gain_per_day_pct


def label_from_gain_per_day(
    pnl_pct: float,
    holding_days: float | None,
    label_cfg: LabelConfig | None = None,
) -> str:
    """Map realized P&L + holding to big_winner / stall / big_loser."""
    cfg = _resolve_label_config(label_cfg)
    gpd = gain_per_day_pct(pnl_pct, holding_days)
    if gpd >= cfg.success_min_profit_per_day_pct:
        return "big_winner"
    if gpd >= cfg.stall_min_gain_per_day_pct:
        return "stall"
    return "big_loser"


def _label_reason(
    pnl_pct: float,
    holding_days: float | None,
    label_3class: str,
    label_cfg: LabelConfig | None = None,
) -> str:
    cfg = _resolve_label_config(label_cfg)
    holding = max(holding_days or 0.0, 1.0)
    gpd = gain_per_day_pct(pnl_pct, holding_days)
    if label_3class == "big_winner":
        return (
            f"gain/day {gpd:.2f}% ≥ {cfg.success_min_profit_per_day_pct:.2f}% "
            f"(P&L {_fmt_pct(pnl_pct)} over {holding:.1f} days)"
        )
    if label_3class == "stall":
        return (
            f"gain/day {gpd:.2f}% in stall band "
            f"[{cfg.stall_min_gain_per_day_pct:.2f}%, {cfg.success_min_profit_per_day_pct:.2f}%) "
            f"(P&L {_fmt_pct(pnl_pct)} over {holding:.1f} days)"
        )
    return (
        f"gain/day {gpd:.2f}% < {cfg.stall_min_gain_per_day_pct:.2f}% "
        f"(P&L {_fmt_pct(pnl_pct)} over {holding:.1f} days)"
    )


def _fmt_pct(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def explain_classification(
    *,
    pnl_pct: float | None,
    holding_days: float | None,
    exit_reason: str | None,
    label_3class: str,
    result: str,
    label_cfg: LabelConfig | None = None,
) -> str:
    """Human-readable rationale for win/loss vs 3-class label on a closed trade."""
    cfg = _resolve_label_config(label_cfg)
    parts: list[str] = []

    if pnl_pct is None:
        parts.append("Realized GBP P&L is unavailable.")
    elif abs(pnl_pct) < FLAT_PNL_PCT_THRESHOLD:
        parts.append(
            f"Result {result.upper()}: realized P&L {_fmt_pct(pnl_pct)} is within "
            f"±{FLAT_PNL_PCT_THRESHOLD}% (flat band)."
        )
    elif pnl_pct > 0:
        parts.append(
            f"Result WIN: realized GBP P&L {_fmt_pct(pnl_pct)} is above +{FLAT_PNL_PCT_THRESHOLD}%."
        )
    else:
        parts.append(
            f"Result LOSS: realized GBP P&L {_fmt_pct(pnl_pct)} is below −{FLAT_PNL_PCT_THRESHOLD}%."
        )

    if pnl_pct is not None and label_3class in {"big_winner", "stall", "big_loser"}:
        parts.append(
            f"Classification {label_3class}: {_label_reason(pnl_pct, holding_days, label_3class, cfg)}."
        )
    elif label_3class == "big_loser" and exit_reason == EXIT_REASON_HARD_STOP:
        parts.append("Classification big_loser: hard stop exit without finalized P&L (learning pipeline only).")
    elif label_3class == "stall":
        parts.append("Classification stall: stagnation exit without finalized P&L.")
    else:
        parts.append(f"Classification {label_3class}: realized P&L unavailable.")

    parts.append(
        "Exit mechanism (stop, trailing lock, market, etc.) does not override "
        "the label once realized GBP P&L is known."
    )

    if exit_reason:
        parts.append(f"Exit mapped to “{exit_label(exit_reason)}” ({exit_reason}).")

    return " ".join(parts)


def derive_label_3class(
    *,
    pnl_pct: float | None,
    holding_days: float | None,
    exit_reason: str | None,
    label_cfg: LabelConfig | None = None,
    allow_stop_without_realized: bool = False,
) -> str:
    """Map a trade to big_winner / stall / big_loser using unified gain/day bands.

    When ``pnl_pct`` is known, gain/day always wins over exit-mechanism heuristics.
    Closed trades never return ``neutral``.
    """
    if pnl_pct is not None:
        return label_from_gain_per_day(pnl_pct, holding_days, label_cfg)

    if allow_stop_without_realized and exit_reason == EXIT_REASON_HARD_STOP:
        return "big_loser"
    if exit_reason == EXIT_REASON_STAGNATION:
        return "stall"
    return "stall"


def simple_result(pnl_pct: float | None) -> str:
    """Win / loss / flat from realized P&L."""
    if pnl_pct is None:
        return "flat"
    if abs(pnl_pct) < FLAT_PNL_PCT_THRESHOLD:
        return "flat"
    return "win" if pnl_pct > 0 else "loss"


def exit_label(exit_reason: str, *, sell_order_type: str | None = None) -> str:
    """Human-readable exit label for UI."""
    if exit_reason in EXIT_LABELS:
        return EXIT_LABELS[exit_reason]
    if (sell_order_type or "").lower() == "stop":
        return EXIT_LABELS[EXIT_REASON_HARD_STOP]
    return EXIT_LABELS[EXIT_REASON_MANUAL]


def weighted_quote_return_pct(
    buy_legs: list[tuple[float, float]],
    sell_quote: float | None,
) -> float | None:
    """USD (or native quote) return % from weighted buy quotes to sell quote."""
    if sell_quote is None or not buy_legs:
        return None
    total_qty = sum(qty for qty, _ in buy_legs if qty > 0)
    if total_qty <= 0:
        return None
    avg_buy = sum(qty * price for qty, price in buy_legs if qty > 0) / total_qty
    if avg_buy <= 0:
        return None
    return (sell_quote - avg_buy) / avg_buy * 100.0
