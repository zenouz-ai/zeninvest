"""Tests for the risk agent — all rules as pure functions."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.data.models import Base
from src.agents.risk.risk_manager import RiskManager


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def mock_get_session(db_session):
    with patch("src.agents.risk.risk_manager.get_session", return_value=db_session):
        yield


@pytest.fixture
def risk_mgr():
    return RiskManager()


class TestMaxSingleStock:
    def test_within_limit(self, risk_mgr):
        result = risk_mgr.check_max_single_stock("AAPL", 10.0, {})
        assert result.passed

    def test_exceeds_limit(self, risk_mgr):
        result = risk_mgr.check_max_single_stock("AAPL", 20.0, {})
        assert not result.passed
        assert result.adjusted_allocation == 15.0

    def test_at_limit(self, risk_mgr):
        result = risk_mgr.check_max_single_stock("AAPL", 15.0, {})
        assert result.passed


class TestMaxSector:
    def test_within_limit(self, risk_mgr):
        result = risk_mgr.check_max_sector("AAPL", "Technology", 10.0, {"Technology": 15.0})
        assert result.passed

    def test_exceeds_limit(self, risk_mgr):
        result = risk_mgr.check_max_sector("AAPL", "Technology", 15.0, {"Technology": 25.0})
        assert not result.passed
        assert result.adjusted_allocation == 10.0  # 35 - 25 = 10% room

    def test_empty_sector(self, risk_mgr):
        result = risk_mgr.check_max_sector("AAPL", "Technology", 10.0, {})
        assert result.passed


class TestCorrelation:
    def test_low_correlation(self, risk_mgr):
        import numpy as np
        np.random.seed(42)
        returns = {
            "AAPL": np.random.randn(50).tolist(),
            "XOM": np.random.randn(50).tolist(),
        }
        result = risk_mgr.check_correlation(returns)
        assert result.passed

    def test_high_correlation(self, risk_mgr):
        base = list(range(50))
        returns = {
            "AAPL": [float(x) for x in base],
            "MSFT": [float(x + 0.01) for x in base],  # Nearly identical
        }
        result = risk_mgr.check_correlation(returns)
        assert not result.passed

    def test_single_position(self, risk_mgr):
        result = risk_mgr.check_correlation({"AAPL": [1.0, 2.0, 3.0]})
        assert result.passed

    def test_insufficient_data(self, risk_mgr):
        result = risk_mgr.check_correlation({"AAPL": [1.0], "MSFT": [2.0]})
        assert result.passed


class TestDrawdown:
    def test_no_drawdown(self, risk_mgr):
        result = risk_mgr.check_drawdown(10000, 10000)
        assert result.passed

    def test_small_drawdown(self, risk_mgr):
        # 3% drawdown — OK
        result = risk_mgr.check_drawdown(9700, 10000)
        assert result.passed

    def test_cautious_drawdown(self, risk_mgr):
        # 6% drawdown — CAUTIOUS warning
        result = risk_mgr.check_drawdown(9400, 10000)
        assert result.passed  # Still passes but message indicates CAUTIOUS
        assert "CAUTIOUS" in result.message

    def test_halt_drawdown(self, risk_mgr):
        # 16% drawdown — HALT
        result = risk_mgr.check_drawdown(8400, 10000)
        assert not result.passed
        assert "HALT" in result.message

    def test_no_peak(self, risk_mgr):
        result = risk_mgr.check_drawdown(10000, 0)
        assert result.passed


class TestDrawdownState:
    def test_active(self, risk_mgr):
        assert risk_mgr.get_drawdown_state(10000, 10000) == "ACTIVE"

    def test_cautious(self, risk_mgr):
        assert risk_mgr.get_drawdown_state(9400, 10000) == "CAUTIOUS"

    def test_halted(self, risk_mgr):
        assert risk_mgr.get_drawdown_state(8400, 10000) == "HALTED"


class TestVixLimit:
    def test_normal_vix(self, risk_mgr):
        result = risk_mgr.check_vix_limit(18.0, 10.0)
        assert result.passed

    def test_high_vix(self, risk_mgr):
        result = risk_mgr.check_vix_limit(28.0, 10.0)
        assert not result.passed
        assert result.adjusted_allocation == 8.0

    def test_extreme_vix(self, risk_mgr):
        result = risk_mgr.check_vix_limit(40.0, 10.0)
        assert not result.passed
        assert result.adjusted_allocation == 5.0

    def test_vix_unavailable(self, risk_mgr):
        result = risk_mgr.check_vix_limit(None, 10.0)
        assert result.passed

    def test_high_vix_small_position(self, risk_mgr):
        result = risk_mgr.check_vix_limit(28.0, 5.0)
        assert result.passed


class TestDailyLossHalt:
    def test_no_loss(self, risk_mgr):
        result = risk_mgr.check_daily_loss_halt(0.5, None)
        assert result.passed

    def test_loss_exceeds_limit(self, risk_mgr):
        result = risk_mgr.check_daily_loss_halt(-2.5, None)
        assert not result.passed

    def test_halt_active(self, risk_mgr):
        future = datetime.utcnow() + timedelta(hours=12)
        result = risk_mgr.check_daily_loss_halt(0.0, future)
        assert not result.passed

    def test_halt_expired(self, risk_mgr):
        past = datetime.utcnow() - timedelta(hours=1)
        result = risk_mgr.check_daily_loss_halt(0.0, past)
        assert result.passed


class TestCashFloor:
    def test_sufficient_cash(self, risk_mgr):
        result = risk_mgr.check_cash_floor(25.0, 10.0)
        assert result.passed

    def test_insufficient_cash(self, risk_mgr):
        result = risk_mgr.check_cash_floor(15.0, 10.0)
        assert not result.passed
        assert result.adjusted_allocation == 5.0  # 15 - 10 = 5% max

    def test_exact_floor(self, risk_mgr):
        result = risk_mgr.check_cash_floor(20.0, 10.0)
        assert result.passed


class TestMinPositions:
    def test_enough_positions(self, risk_mgr):
        result = risk_mgr.check_min_positions(8, "SELL")
        assert result.passed

    def test_at_minimum(self, risk_mgr):
        result = risk_mgr.check_min_positions(5, "SELL")
        assert not result.passed

    def test_buy_always_ok(self, risk_mgr):
        result = risk_mgr.check_min_positions(3, "BUY")
        assert result.passed


class TestCautiousState:
    def test_active_state(self, risk_mgr):
        result = risk_mgr.check_cautious_state("ACTIVE", "BUY", 10.0)
        assert result.passed

    def test_cautious_new_position(self, risk_mgr):
        result = risk_mgr.check_cautious_state("CAUTIOUS", "BUY", 5.0, is_winner=False)
        assert not result.passed

    def test_cautious_add_to_winner(self, risk_mgr):
        result = risk_mgr.check_cautious_state("CAUTIOUS", "BUY", 5.0, is_winner=True)
        assert result.passed

    def test_cautious_over_limit(self, risk_mgr):
        result = risk_mgr.check_cautious_state("CAUTIOUS", "BUY", 10.0, is_winner=True)
        assert not result.passed
        assert result.adjusted_allocation == 8.0


class TestEvaluateTrade:
    def _default_params(self, **overrides):
        params = dict(
            ticker="AAPL",
            action="BUY",
            proposed_allocation_pct=5.0,
            sector="Technology",
            current_portfolio={"MSFT": 8.0},
            sector_allocations={"Technology": 15.0},
            portfolio_returns={},
            current_value=10000.0,
            peak_value=10000.0,
            cash_pct=30.0,
            vix=18.0,
            daily_pnl_pct=0.0,
            daily_loss_halt_until=None,
            num_positions=8,
            system_state="ACTIVE",
            cycle_id="test-cycle",
        )
        params.update(overrides)
        return params

    def test_approve_normal_trade(self, risk_mgr):
        verdict = risk_mgr.evaluate_trade(**self._default_params())
        assert verdict.verdict == "APPROVE"

    def test_reject_halted_state(self, risk_mgr):
        verdict = risk_mgr.evaluate_trade(**self._default_params(system_state="HALTED"))
        assert verdict.verdict == "REJECT"
        assert "HALTED" in verdict.reasoning

    def test_resize_on_vix(self, risk_mgr):
        verdict = risk_mgr.evaluate_trade(**self._default_params(vix=30.0, proposed_allocation_pct=10.0))
        assert verdict.verdict == "RESIZE"
        assert verdict.adjusted_allocation_pct == 8.0

    def test_reject_over_stock_limit(self, risk_mgr):
        verdict = risk_mgr.evaluate_trade(**self._default_params(
            proposed_allocation_pct=20.0,
            cash_pct=50.0,
        ))
        assert verdict.verdict == "RESIZE"
        assert verdict.adjusted_allocation_pct == 15.0

    def test_reject_on_halt_drawdown(self, risk_mgr):
        verdict = risk_mgr.evaluate_trade(**self._default_params(
            current_value=8000.0,
            peak_value=10000.0,
        ))
        assert verdict.verdict == "REJECT"
        assert "HALT" in verdict.reasoning

    def test_sell_at_min_positions(self, risk_mgr):
        verdict = risk_mgr.evaluate_trade(**self._default_params(
            action="SELL",
            num_positions=5,
        ))
        assert verdict.verdict == "REJECT"
