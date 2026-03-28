"""Shared portfolio and trade execution service.

Eliminates duplicated portfolio/pricing/validation logic across
SingleTickerRunner, DirectTradeRunner, and CancelCommandRunner.
All runners delegate to PortfolioService for shared operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.agents.execution.t212_client import T212Client
from src.agents.market_data.data_fetcher import DataFetcher
from src.data.database import get_session
from src.data.models import Instrument
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("trade_execution_service")


@dataclass
class TradeIntent:
    """Typed trade intent that all execution paths accept.

    Constructed from TradeCommandIntent (Slack parser) or directly
    from the conversation orchestrator.
    """

    action: str  # BUY, SELL, REVIEW, CANCEL
    ticker_t212: str
    execution_mode: str = "direct"  # direct, strategy, cancel_only
    amount_gbp: float | None = None
    quantity_shares: float | None = None
    force: bool = False
    cancel_order_class: str | None = None
    trigger_strategy: bool = False
    session_id: int | None = None
    turn_id: int | None = None
    raw_message: str = ""
    subject_phrases: list[str] = field(default_factory=list)


class PortfolioService:
    """Shared portfolio operations used by all trade execution paths.

    Owns: price extraction, FX conversion, portfolio data fetch,
    cash queries, total value computation, company profiles.
    """

    def __init__(
        self,
        *,
        t212_client: T212Client | None = None,
        data_fetcher: DataFetcher | None = None,
    ) -> None:
        self.settings = get_settings()
        self._t212_client = t212_client
        self._data_fetcher = data_fetcher

    @property
    def t212_client(self) -> T212Client:
        if self._t212_client is None:
            self._t212_client = T212Client()
        return self._t212_client

    @property
    def data_fetcher(self) -> DataFetcher:
        if self._data_fetcher is None:
            self._data_fetcher = DataFetcher()
        return self._data_fetcher

    def close(self) -> None:
        if self._data_fetcher:
            self._data_fetcher.close()
        if self._t212_client:
            self._t212_client.close()

    # ------------------------------------------------------------------
    # Price extraction
    # ------------------------------------------------------------------

    def extract_price(self, stock_data: dict[str, Any]) -> float | None:
        """Extract current price from stock analysis data."""
        indicators = stock_data.get("indicators", {})
        if indicators and isinstance(indicators, dict):
            price = indicators.get("current_price") or indicators.get("close")
            if price is not None:
                return float(price)
        fundamentals = stock_data.get("fundamentals", {})
        if fundamentals and isinstance(fundamentals, dict):
            price = fundamentals.get("currentPrice") or fundamentals.get("previousClose")
            if price is not None:
                return float(price)
        return None

    # ------------------------------------------------------------------
    # FX conversion
    # ------------------------------------------------------------------

    def compute_fx_price_gbp(
        self, current_price: float, ticker: str, portfolio_data: dict[str, Any] | None
    ) -> float:
        """Convert native instrument price into GBP for quantity sizing."""
        if not self.settings.fx_aware_quantity:
            return current_price
        if "_UK_EQ" in ticker:
            return current_price / 100
        if "_US_EQ" not in ticker:
            return current_price
        positions = (portfolio_data or {}).get("positions", [])
        invested_gbp = float(
            (
                (((portfolio_data or {}).get("account_summary") or {}).get("investments") or {})
                .get("currentValue", 0)
            )
            or (portfolio_data or {}).get("invested", 0)
            or 0
        )
        scale = self.compute_position_value_scale(positions, invested_gbp)
        return current_price * scale

    @staticmethod
    def compute_position_value_scale(positions: list[dict[str, Any]], invested_gbp: float) -> float:
        """Infer GBP/native-currency scale from T212 portfolio values."""
        if invested_gbp <= 0 or not positions:
            return 1.0
        native_total = 0.0
        for pos in positions:
            qty = float(pos.get("quantity", 0) or 0)
            px = float(pos.get("currentPrice", 0) or 0)
            native_total += qty * px
        if native_total <= 0:
            return 1.0
        return invested_gbp / native_total

    # ------------------------------------------------------------------
    # Cash extraction
    # ------------------------------------------------------------------

    @staticmethod
    def extract_available_cash(cash_data: Any) -> float:
        """Extract the free/available-to-trade cash from a T212 cash payload."""
        if isinstance(cash_data, dict):
            return float(cash_data.get("free") or cash_data.get("availableToTrade") or 0)
        return float(cash_data or 0)

    @staticmethod
    def extract_reserved_cash(cash_data: Any) -> float:
        """Extract reserved cash from a T212 cash payload."""
        if isinstance(cash_data, dict):
            return float(
                cash_data.get("reservedForOrders")
                or cash_data.get("blocked")
                or cash_data.get("reserved")
                or 0
            )
        return 0.0

    # ------------------------------------------------------------------
    # Total value computation
    # ------------------------------------------------------------------

    def get_total_value_gbp(
        self,
        account_summary: dict[str, Any],
        cash_data: Any,
        positions: list[dict[str, Any]],
    ) -> float:
        """Compute total value, preferring account summary and falling back to cash + positions."""
        total_value_raw = account_summary.get("totalValue")
        if total_value_raw is not None:
            return float(total_value_raw)

        cash = self.extract_available_cash(cash_data)
        reserved = self.extract_reserved_cash(cash_data)
        invested = float((account_summary.get("investments") or {}).get("currentValue", 0) or 0)
        if invested <= 0:
            invested = sum(float(p.get("currentValue", 0) or 0) for p in positions)
        total = cash + invested + reserved
        return total if total > 0 else 10000.0

    # ------------------------------------------------------------------
    # Portfolio data fetch
    # ------------------------------------------------------------------

    def get_portfolio_data(self, caller: str = "trade_service") -> dict[str, Any]:
        """Get portfolio summary from T212 broker."""
        try:
            try:
                account_summary = self.t212_client.get_account_summary()
            except Exception as e:
                logger.warning("Account summary unavailable for %s: %s", caller, e)
                account_summary = {}

            try:
                cash_data = self.t212_client.get_cash()
            except Exception as e:
                logger.warning("Cash endpoint unavailable for %s, falling back to summary cash: %s", caller, e)
                cash_data = account_summary.get("cash", {})

            try:
                positions = self.t212_client.get_portfolio()
            except Exception:
                positions = []

            total = self.get_total_value_gbp(account_summary, cash_data, positions)
            cash = self.extract_available_cash(cash_data if cash_data else account_summary.get("cash", {}))
            cash_pct = (cash / total * 100) if total > 0 else 10.0
            invested = float(((account_summary.get("investments") or {}).get("currentValue", 0)) or 0)
            return {
                "total_value": total,
                "cash": cash,
                "cash_pct": cash_pct,
                "invested": invested,
                "positions": positions,
                "account_summary": account_summary,
            }
        except Exception:
            return {"total_value": 10000, "cash": 1000, "cash_pct": 10.0}

    def get_available_cash_gbp(self) -> float:
        """Return the free/available-to-trade cash balance."""
        try:
            cash_data = self.t212_client.get_cash()
            cash = self.extract_available_cash(cash_data)
            if cash > 0:
                return cash
        except Exception as e:
            logger.warning("Cash endpoint unavailable during preflight validation: %s", e)

        account_summary = self.t212_client.get_account_summary()
        return self.extract_available_cash(account_summary.get("cash", {}))

    # ------------------------------------------------------------------
    # Company/sector lookup
    # ------------------------------------------------------------------

    @staticmethod
    def get_company_profile(ticker_t212: str) -> str:
        """Get company profile from Instrument table."""
        session = get_session()
        try:
            inst = session.query(Instrument).filter(Instrument.ticker == ticker_t212).first()
            if inst:
                parts = []
                if inst.name:
                    parts.append(f"{inst.name}")
                if inst.sector:
                    parts.append(f"Sector: {inst.sector}")
                if inst.industry:
                    parts.append(f"Industry: {inst.industry}")
                if inst.business_summary:
                    parts.append(inst.business_summary[:500])
                return " | ".join(parts) if parts else ""
            return ""
        except Exception:
            return ""
        finally:
            session.close()

    @staticmethod
    def get_sector(ticker_t212: str) -> str:
        """Get sector for a ticker from Instrument table."""
        session = get_session()
        try:
            inst = session.query(Instrument).filter(Instrument.ticker == ticker_t212).first()
            return inst.sector or "Unknown" if inst else "Unknown"
        except Exception:
            return "Unknown"
        finally:
            session.close()
