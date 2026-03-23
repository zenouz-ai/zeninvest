"""Tests for portfolio snapshot normalization to GBP values."""

from unittest.mock import MagicMock, patch

from src.orchestrator.main import Orchestrator


# ---------------------------------------------------------------------------
# _compute_fx_price_gbp tests
# ---------------------------------------------------------------------------

def _make_orchestrator(fx_aware: bool = True) -> Orchestrator:
    """Build a minimal Orchestrator with mocked dependencies."""
    with patch("src.orchestrator.main.get_settings") as mock_gs:
        mock_settings = MagicMock()
        mock_settings.fx_aware_quantity = fx_aware
        mock_gs.return_value = mock_settings
        orch = Orchestrator.__new__(Orchestrator)
        orch.settings = mock_settings
        return orch


def test_compute_fx_price_gbp_us_eq_applies_scale():
    """USD stock price is multiplied by account-level GBP/USD scale."""
    orch = _make_orchestrator(fx_aware=True)
    positions = [
        {"quantity": 2.0, "currentPrice": 200.0},  # $200 USD each
    ]
    # invested_gbp = £310, native_total = 400 USD → scale = 310/400 = 0.775
    portfolio_data = {
        "positions": positions,
        "account_summary": {"investments": {"currentValue": 310.0}},
    }
    price_gbp = orch._compute_fx_price_gbp(232.0, "MPC_US_EQ", portfolio_data)
    expected_scale = 310.0 / (2.0 * 200.0)
    assert round(price_gbp, 6) == round(232.0 * expected_scale, 6)


def test_compute_fx_price_gbp_uk_eq_divides_by_100():
    """UK stock price (GBX pence) is divided by 100 to get GBP."""
    orch = _make_orchestrator(fx_aware=True)
    price_gbp = orch._compute_fx_price_gbp(1500.0, "BP._UK_EQ", {})
    assert price_gbp == 15.0  # 1500 GBX → £15.00


def test_compute_fx_price_gbp_unknown_suffix_no_conversion():
    """Unknown ticker suffix — no conversion applied."""
    orch = _make_orchestrator(fx_aware=True)
    price_gbp = orch._compute_fx_price_gbp(100.0, "FOO_AU_EQ", {})
    assert price_gbp == 100.0


def test_compute_fx_price_gbp_disabled_returns_native():
    """When fx_aware_quantity=False the native price is returned unchanged."""
    orch = _make_orchestrator(fx_aware=False)
    price_gbp = orch._compute_fx_price_gbp(232.0, "MPC_US_EQ", {
        "positions": [{"quantity": 2.0, "currentPrice": 200.0}],
        "account_summary": {"investments": {"currentValue": 310.0}},
    })
    assert price_gbp == 232.0  # No conversion


def test_compute_fx_price_gbp_empty_portfolio_falls_back():
    """When portfolio is empty (first trade), scale=1.0, price returned unchanged."""
    orch = _make_orchestrator(fx_aware=True)
    price_gbp = orch._compute_fx_price_gbp(232.0, "MPC_US_EQ", {"positions": []})
    assert price_gbp == 232.0  # scale defaults to 1.0


def test_compute_position_value_scale_uses_invested_gbp():
    positions = [
        {"quantity": 3.32, "currentPrice": 237.68},
        {"quantity": 2.69, "currentPrice": 285.57},
    ]
    native_total = 3.32 * 237.68 + 2.69 * 285.57
    invested_gbp = 1200.0
    scale = Orchestrator._compute_position_value_scale(positions, invested_gbp)
    assert round(scale, 8) == round(invested_gbp / native_total, 8)


def test_normalize_position_walletimpact_absent_uses_scale_and_ppl():
    pos = {
        "ticker": "JNJ_US_EQ",
        "quantity": 3.32,
        "currentPrice": 237.68,
        "averagePrice": 244.50,
        "ppl": -20.24,
        "fxPpl": -3.29,
    }
    # Simulate USD->GBP scale inferred from account-level invested values
    scale = 0.75
    norm = Orchestrator._normalize_position_for_snapshot(pos, value_scale=scale)

    assert norm["ticker"] == "JNJ_US_EQ"
    assert round(norm["value_gbp"], 6) == round(3.32 * 237.68 * scale, 6)
    assert round(norm["pnl_gbp"], 6) == round(-20.24 + -3.29, 6)
    # Percentage should use scaled average cost fallback
    expected_total_cost = 244.50 * 3.32 * scale
    expected_pnl_pct = ((-20.24 + -3.29) / expected_total_cost) * 100
    assert round(norm["pnl_pct"], 6) == round(expected_pnl_pct, 6)


def test_normalize_position_prefers_walletimpact_when_available():
    pos = {
        "ticker": "LNG_US_EQ",
        "quantity": 2.69,
        "currentPrice": 285.57,
        "walletImpact": {
            "currentValue": 575.48,
            "unrealizedProfitLoss": 47.06,
            "totalCost": 528.42,
        },
    }
    norm = Orchestrator._normalize_position_for_snapshot(pos, value_scale=0.1)
    # walletImpact should override scale-based fallbacks
    assert norm["value_gbp"] == 575.48
    assert norm["pnl_gbp"] == 47.06
    assert round(norm["pnl_pct"], 6) == round((47.06 / 528.42) * 100, 6)
