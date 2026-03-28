"""Tests for PortfolioService and TradeIntent.

Covers: price extraction, FX conversion, cash extraction, total value,
portfolio data fetch, company/sector lookup, position value scale.
"""

import os
import sys

os.environ.setdefault("INVESTMENT_AGENT_USE_INMEMORY_DB", "1")

from unittest.mock import MagicMock, patch

import pytest

from src.agents.conversation.trade_execution_service import PortfolioService, TradeIntent


# ---------------------------------------------------------------------------
# TradeIntent dataclass
# ---------------------------------------------------------------------------


class TestTradeIntent:
    def test_default_values(self):
        intent = TradeIntent(action="BUY", ticker_t212="AAPL_US_EQ")
        assert intent.action == "BUY"
        assert intent.ticker_t212 == "AAPL_US_EQ"
        assert intent.execution_mode == "direct"
        assert intent.amount_gbp is None
        assert intent.quantity_shares is None
        assert intent.force is False
        assert intent.cancel_order_class is None
        assert intent.trigger_strategy is False
        assert intent.subject_phrases == []

    def test_full_construction(self):
        intent = TradeIntent(
            action="SELL",
            ticker_t212="MSFT_US_EQ",
            execution_mode="strategy",
            amount_gbp=1000.0,
            quantity_shares=5.0,
            force=True,
            cancel_order_class="buy",
            trigger_strategy=True,
            session_id=42,
            turn_id=7,
            raw_message="force sell MSFT",
            subject_phrases=["MSFT", "Microsoft"],
        )
        assert intent.action == "SELL"
        assert intent.force is True
        assert intent.session_id == 42
        assert intent.subject_phrases == ["MSFT", "Microsoft"]


# ---------------------------------------------------------------------------
# PortfolioService — price extraction
# ---------------------------------------------------------------------------


class TestExtractPrice:
    def setup_method(self):
        self.svc = PortfolioService()

    def test_extract_from_indicators_current_price(self):
        data = {"indicators": {"current_price": 175.50}}
        assert self.svc.extract_price(data) == 175.50

    def test_extract_from_indicators_close(self):
        data = {"indicators": {"close": 174.00}}
        assert self.svc.extract_price(data) == 174.00

    def test_extract_from_fundamentals_current_price(self):
        data = {"indicators": {}, "fundamentals": {"currentPrice": 180.25}}
        assert self.svc.extract_price(data) == 180.25

    def test_extract_from_fundamentals_previous_close(self):
        data = {"indicators": {}, "fundamentals": {"previousClose": 179.00}}
        assert self.svc.extract_price(data) == 179.00

    def test_returns_none_when_empty(self):
        assert self.svc.extract_price({}) is None
        assert self.svc.extract_price({"indicators": {}, "fundamentals": {}}) is None

    def test_indicators_preferred_over_fundamentals(self):
        data = {
            "indicators": {"current_price": 175.50},
            "fundamentals": {"currentPrice": 180.00},
        }
        assert self.svc.extract_price(data) == 175.50


# ---------------------------------------------------------------------------
# PortfolioService — FX conversion
# ---------------------------------------------------------------------------


class TestComputeFxPriceGbp:
    def setup_method(self):
        self.svc = PortfolioService()

    def test_fx_disabled_returns_raw_price(self):
        with patch.object(self.svc, "settings") as mock_settings:
            mock_settings.fx_aware_quantity = False
            result = self.svc.compute_fx_price_gbp(100.0, "AAPL_US_EQ", None)
            assert result == 100.0

    def test_uk_eq_divides_by_100(self):
        with patch.object(self.svc, "settings") as mock_settings:
            mock_settings.fx_aware_quantity = True
            result = self.svc.compute_fx_price_gbp(15000.0, "BP._UK_EQ", None)
            assert result == 150.0

    def test_us_eq_uses_scale(self):
        with patch.object(self.svc, "settings") as mock_settings:
            mock_settings.fx_aware_quantity = True
            portfolio = {
                "positions": [
                    {"quantity": 10, "currentPrice": 100.0},
                ],
                "account_summary": {"investments": {"currentValue": 800.0}},
            }
            result = self.svc.compute_fx_price_gbp(100.0, "AAPL_US_EQ", portfolio)
            # scale = 800 / (10*100) = 0.8
            assert result == pytest.approx(80.0)

    def test_non_us_non_uk_returns_raw(self):
        with patch.object(self.svc, "settings") as mock_settings:
            mock_settings.fx_aware_quantity = True
            result = self.svc.compute_fx_price_gbp(50.0, "SAP_DE_EQ", None)
            assert result == 50.0


# ---------------------------------------------------------------------------
# PortfolioService — position value scale
# ---------------------------------------------------------------------------


class TestComputePositionValueScale:
    def test_positive_values(self):
        positions = [
            {"quantity": 10, "currentPrice": 100.0},
            {"quantity": 5, "currentPrice": 200.0},
        ]
        # native_total = 10*100 + 5*200 = 2000
        # scale = 1600 / 2000 = 0.8
        assert PortfolioService.compute_position_value_scale(positions, 1600.0) == pytest.approx(0.8)

    def test_zero_invested_returns_one(self):
        assert PortfolioService.compute_position_value_scale([], 0) == 1.0

    def test_empty_positions_returns_one(self):
        assert PortfolioService.compute_position_value_scale([], 1000.0) == 1.0

    def test_zero_native_total_returns_one(self):
        positions = [{"quantity": 0, "currentPrice": 0}]
        assert PortfolioService.compute_position_value_scale(positions, 1000.0) == 1.0


# ---------------------------------------------------------------------------
# PortfolioService — cash extraction
# ---------------------------------------------------------------------------


class TestExtractCash:
    def test_available_cash_from_free(self):
        assert PortfolioService.extract_available_cash({"free": 5000.0}) == 5000.0

    def test_available_cash_from_available_to_trade(self):
        assert PortfolioService.extract_available_cash({"availableToTrade": 3000.0}) == 3000.0

    def test_available_cash_from_scalar(self):
        assert PortfolioService.extract_available_cash(2500.0) == 2500.0

    def test_available_cash_none(self):
        assert PortfolioService.extract_available_cash(None) == 0.0

    def test_reserved_cash_from_dict(self):
        assert PortfolioService.extract_reserved_cash({"reservedForOrders": 150.0}) == 150.0

    def test_reserved_cash_blocked(self):
        assert PortfolioService.extract_reserved_cash({"blocked": 75.0}) == 75.0

    def test_reserved_cash_scalar(self):
        assert PortfolioService.extract_reserved_cash(100.0) == 0.0


# ---------------------------------------------------------------------------
# PortfolioService — total value computation
# ---------------------------------------------------------------------------


class TestGetTotalValueGbp:
    def setup_method(self):
        self.svc = PortfolioService()

    def test_uses_total_value_when_present(self):
        result = self.svc.get_total_value_gbp(
            {"totalValue": 25000.0}, {"free": 5000.0}, []
        )
        assert result == 25000.0

    def test_fallback_cash_plus_invested(self):
        result = self.svc.get_total_value_gbp(
            {"investments": {"currentValue": 15000.0}},
            {"free": 5000.0, "reservedForOrders": 500.0},
            [],
        )
        assert result == 20500.0

    def test_fallback_positions_sum(self):
        positions = [
            {"currentValue": 8000.0},
            {"currentValue": 4000.0},
        ]
        result = self.svc.get_total_value_gbp({}, {"free": 3000.0}, positions)
        assert result == 15000.0

    def test_defaults_to_10000(self):
        result = self.svc.get_total_value_gbp({}, {}, [])
        assert result == 10000.0


# ---------------------------------------------------------------------------
# PortfolioService — company profile and sector
# ---------------------------------------------------------------------------


class TestCompanyProfile:
    @patch("src.agents.conversation.trade_execution_service.get_session")
    def test_returns_profile_string(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_inst = MagicMock()
        mock_inst.name = "Apple Inc."
        mock_inst.sector = "Technology"
        mock_inst.industry = "Consumer Electronics"
        mock_inst.business_summary = "Apple designs and manufactures consumer electronics."
        mock_session.query.return_value.filter.return_value.first.return_value = mock_inst

        result = PortfolioService.get_company_profile("AAPL_US_EQ")
        assert "Apple Inc." in result
        assert "Technology" in result
        assert "Consumer Electronics" in result

    @patch("src.agents.conversation.trade_execution_service.get_session")
    def test_returns_empty_when_not_found(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = None

        assert PortfolioService.get_company_profile("FAKE_US_EQ") == ""

    @patch("src.agents.conversation.trade_execution_service.get_session")
    def test_get_sector(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_inst = MagicMock()
        mock_inst.sector = "Technology"
        mock_session.query.return_value.filter.return_value.first.return_value = mock_inst

        assert PortfolioService.get_sector("AAPL_US_EQ") == "Technology"

    @patch("src.agents.conversation.trade_execution_service.get_session")
    def test_get_sector_unknown(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = None

        assert PortfolioService.get_sector("FAKE_US_EQ") == "Unknown"


# ---------------------------------------------------------------------------
# PortfolioService — get_portfolio_data
# ---------------------------------------------------------------------------


class TestGetPortfolioData:
    def test_returns_structured_data(self):
        mock_t212 = MagicMock()
        mock_t212.get_account_summary.return_value = {
            "totalValue": 20000.0,
            "investments": {"currentValue": 15000.0},
        }
        mock_t212.get_cash.return_value = {"free": 5000.0}
        mock_t212.get_portfolio.return_value = [
            {"ticker": "AAPL_US_EQ", "quantity": 10, "currentPrice": 175.0},
        ]

        svc = PortfolioService(t212_client=mock_t212)
        data = svc.get_portfolio_data(caller="test")

        assert data["total_value"] == 20000.0
        assert data["cash"] == 5000.0
        assert data["cash_pct"] == pytest.approx(25.0)
        assert data["invested"] == 15000.0
        assert len(data["positions"]) == 1

    def test_graceful_degradation_all_endpoints_fail(self):
        mock_t212 = MagicMock()
        mock_t212.get_account_summary.side_effect = Exception("API down")
        mock_t212.get_cash.side_effect = Exception("API down")
        mock_t212.get_portfolio.side_effect = Exception("API down")

        svc = PortfolioService(t212_client=mock_t212)
        data = svc.get_portfolio_data(caller="test")

        # Each inner try/except handles its own failure; the method still returns
        # structured data with safe defaults (total=10000 from get_total_value_gbp fallback)
        assert data["total_value"] == 10000.0
        assert data["cash"] == 0.0
        assert data["positions"] == []


# ---------------------------------------------------------------------------
# PortfolioService — get_available_cash_gbp
# ---------------------------------------------------------------------------


class TestGetAvailableCashGbp:
    def test_cash_from_endpoint(self):
        mock_t212 = MagicMock()
        mock_t212.get_cash.return_value = {"free": 3500.0}

        svc = PortfolioService(t212_client=mock_t212)
        assert svc.get_available_cash_gbp() == 3500.0

    def test_fallback_to_account_summary(self):
        mock_t212 = MagicMock()
        mock_t212.get_cash.side_effect = Exception("timeout")
        mock_t212.get_account_summary.return_value = {
            "cash": {"free": 2800.0}
        }

        svc = PortfolioService(t212_client=mock_t212)
        assert svc.get_available_cash_gbp() == 2800.0
