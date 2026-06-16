"""Trading 212 wallet truth helpers for order fills.

Authoritative GBP amounts come from ``fill.walletImpact.netValue`` in order
history. Native instrument quote prices come from ``fill.price``. Never treat
``filledValue / quantity`` as GBP — for quantity orders it is instrument notional.
"""

from __future__ import annotations

from typing import Any

from src.data.models import Order


def wallet_amount_gbp(net_value: float | int | None) -> float | None:
    """Absolute GBP wallet amount from T212 ``walletImpact.netValue`` (signed)."""
    if net_value is None:
        return None
    try:
        return abs(float(net_value))
    except (TypeError, ValueError):
        return None


def parse_t212_history_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Extract fill + order fields from one T212 history item."""
    if not isinstance(item, dict):
        return None
    fill = item.get("fill")
    order_obj = item.get("order")
    if not isinstance(fill, dict) or not isinstance(order_obj, dict):
        return None

    t212_id = order_obj.get("id") or order_obj.get("orderId")
    if t212_id is None:
        return None

    wallet = fill.get("walletImpact") if isinstance(fill.get("walletImpact"), dict) else {}
    fill_qty_raw = fill.get("quantity")
    fill_price_raw = fill.get("price")
    filled_qty = None
    quote_price = None
    if fill_qty_raw is not None:
        try:
            filled_qty = abs(float(fill_qty_raw))
        except (TypeError, ValueError):
            filled_qty = None
    if fill_price_raw is not None:
        try:
            quote_price = float(fill_price_raw)
        except (TypeError, ValueError):
            quote_price = None

    return {
        "t212_order_id": str(t212_id),
        "quote_fill_price": quote_price,
        "filled_quantity": filled_qty,
        "wallet_value_gbp": wallet_amount_gbp(wallet.get("netValue")),
        "order_status": str(order_obj.get("status") or "").upper(),
        "filled_at": fill.get("filledAt"),
    }


def effective_filled_shares(order: Order) -> float:
    """Shares actually filled on this order."""
    if order.filled_quantity is not None and float(order.filled_quantity) > 0:
        return abs(float(order.filled_quantity))
    if order.status in {"filled", "dry_run"}:
        return abs(float(order.quantity or 0))
    return 0.0


def quote_fill_price(order: Order) -> float | None:
    """Native instrument quote price at fill (USD for US names)."""
    if order.price is not None:
        return float(order.price)
    if order.decision_price is not None:
        return float(order.decision_price)
    return None


def wallet_value_gbp(order: Order) -> float | None:
    """GBP wallet debit/credit for this order when known."""
    if order.value_gbp is None:
        return None
    try:
        value = float(order.value_gbp)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def wallet_per_share_gbp(order: Order) -> float | None:
    shares = effective_filled_shares(order)
    wallet = wallet_value_gbp(order)
    if shares > 0 and wallet is not None:
        return wallet / shares
    return None


def fifo_wallet_slice(order: Order, quantity_matched: float) -> float | None:
    """Proportional GBP wallet for a FIFO slice of a buy/sell order."""
    shares = effective_filled_shares(order)
    wallet = wallet_value_gbp(order)
    if shares <= 0 or wallet is None or quantity_matched <= 0:
        return None
    return wallet * (quantity_matched / shares)
