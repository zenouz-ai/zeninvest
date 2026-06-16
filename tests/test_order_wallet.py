"""Tests for T212 wallet truth helpers."""

from __future__ import annotations

import pytest

from src.agents.execution.order_wallet import (
    effective_filled_shares,
    fifo_wallet_slice,
    parse_t212_history_item,
    wallet_amount_gbp,
)
from src.data.models import Order


def test_wallet_amount_gbp_abs():
    assert wallet_amount_gbp(-303.39) == 303.39
    assert wallet_amount_gbp(386.16) == 386.16


def test_parse_t212_history_item_wallet_and_quote():
    item = {
        "fill": {
            "price": 16.09,
            "quantity": -24.0,
            "walletImpact": {"netValue": 279.12, "currency": "GBP"},
        },
        "order": {"id": 999, "status": "FILLED", "quantity": -24.0},
    }
    parsed = parse_t212_history_item(item)
    assert parsed is not None
    assert parsed["t212_order_id"] == "999"
    assert parsed["quote_fill_price"] == 16.09
    assert parsed["filled_quantity"] == 24.0
    assert parsed["wallet_value_gbp"] == 279.12


def test_effective_filled_shares_prefers_filled_quantity():
    order = Order(
        ticker="X_US_EQ",
        action="BUY",
        order_type="market",
        quantity=27.0,
        filled_quantity=24.0,
        status="filled",
    )
    assert effective_filled_shares(order) == 24.0


def test_fifo_wallet_slice():
    order = Order(
        ticker="X_US_EQ",
        action="BUY",
        order_type="market",
        quantity=27.0,
        filled_quantity=27.0,
        value_gbp=341.32,
        status="filled",
    )
    assert fifo_wallet_slice(order, 24.0) == pytest.approx(341.32 * 24 / 27, rel=1e-4)
