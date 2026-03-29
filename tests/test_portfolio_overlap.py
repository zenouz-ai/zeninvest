"""Tests for candidate-vs-portfolio overlap analysis."""

from src.agents.risk.portfolio_overlap import analyze_candidate_portfolio_overlap


def test_high_correlation_overlap() -> None:
    candidate = [100 + idx for idx in range(70)]
    positions = {
        "MSFT_US_EQ": [100.5 + idx for idx in range(70)],
        "NVDA_US_EQ": [50 + idx * 0.5 for idx in range(70)],
    }
    result = analyze_candidate_portfolio_overlap(candidate, positions, threshold=0.6, lookback_days=60)
    assert result["high_correlation_flag"] is True
    assert result["avg_correlation"] is not None
    assert result["top_overlaps"][0]["ticker"] == "MSFT_US_EQ"


def test_low_correlation_overlap() -> None:
    candidate = [100, 102, 101, 103, 100, 104, 99, 105] * 10
    positions = {
        "XOM_US_EQ": [70, 68, 71, 69, 72, 68, 73, 67] * 10,
    }
    result = analyze_candidate_portfolio_overlap(candidate, positions, threshold=0.6, lookback_days=60)
    assert result["high_correlation_flag"] is False


def test_negative_correlation_is_not_flagged() -> None:
    candidate = [100, 103, 99, 104, 98, 105, 97, 106] * 9
    positions = {
        "TLT_US_EQ": [100, 97, 101, 96, 102, 95, 103, 94] * 9,
    }
    result = analyze_candidate_portfolio_overlap(candidate, positions, threshold=0.6, lookback_days=60)
    assert result["avg_correlation"] is not None
    assert result["high_correlation_flag"] is False


def test_insufficient_history_returns_empty_payload() -> None:
    result = analyze_candidate_portfolio_overlap(
        [100, 101, 102],
        {"MSFT_US_EQ": [99, 100, 101]},
        min_history_days=20,
    )
    assert result["avg_correlation"] is None
    assert result["top_overlaps"] == []


def test_empty_portfolio_returns_empty_payload() -> None:
    result = analyze_candidate_portfolio_overlap([100 + idx for idx in range(70)], {})
    assert result["avg_correlation"] is None
    assert result["high_correlation_flag"] is False
