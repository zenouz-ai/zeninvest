"""Tests for portfolio snapshot normalization to GBP values."""

from src.orchestrator.main import Orchestrator


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
