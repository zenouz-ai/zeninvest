"""Main data fetcher — orchestrates yfinance, Finnhub, Alpha Vantage, and T212."""

import json
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from src.agents.market_data.alpha_vantage_client import AlphaVantageClient
from src.agents.market_data.finnhub_client import FinnhubClient
from src.agents.market_data.fundamentals import get_fundamentals
from src.agents.market_data.indicators import calculate_indicators, calculate_relative_strength
from src.data.database import get_session
from src.data.models import Instrument, MarketDataCache, NewsSentimentCache
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("data_fetcher")


class DataFetcher:
    """Unified data fetcher for all market data sources."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._finnhub: FinnhubClient | None = None
        self._alpha_vantage: AlphaVantageClient | None = None

    @property
    def finnhub(self) -> FinnhubClient:
        if self._finnhub is None:
            self._finnhub = FinnhubClient()
        return self._finnhub

    @property
    def alpha_vantage(self) -> AlphaVantageClient:
        if self._alpha_vantage is None:
            self._alpha_vantage = AlphaVantageClient()
        return self._alpha_vantage

    # --- yfinance data ---

    def get_ohlcv(
        self,
        ticker: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Fetch OHLCV data from yfinance."""
        try:
            df = yf.download(ticker, period=period, interval=interval, progress=False)
            if df.empty:
                logger.warning(f"No OHLCV data for {ticker}")
                return pd.DataFrame()

            # Flatten MultiIndex columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            return df
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV for {ticker}: {e}")
            return pd.DataFrame()

    def get_benchmark_data(self, period: str = "1y") -> pd.DataFrame:
        """Fetch S&P 500 benchmark data."""
        return self.get_ohlcv(self.settings.benchmark_ticker, period=period)

    def get_macro_data(self) -> dict[str, Any]:
        """Fetch macro indicators: VIX and S&P 500 vs 200-day MA.

        These two inputs drive the market regime classification and risk rules.
        See docs/DATA_RATIONALE.md for why yield spread data was removed.
        """
        result: dict[str, Any] = {}

        # VIX — used by risk rules (position caps) and market regime
        try:
            vix_df = self.get_ohlcv("^VIX", period="5d")
            if not vix_df.empty:
                result["vix"] = float(vix_df["Close"].iloc[-1])
            else:
                result["vix"] = None
        except Exception as e:
            logger.error(f"Failed to fetch VIX: {e}")
            result["vix"] = None

        # S&P 500 vs 200-day MA — used for market regime classification
        try:
            sp_df = self.get_ohlcv("^GSPC", period="1y")
            if not sp_df.empty and len(sp_df) >= 200:
                sp_price = float(sp_df["Close"].iloc[-1])
                sp_200ma = float(sp_df["Close"].rolling(200).mean().iloc[-1])
                result["sp500_price"] = sp_price
                result["sp500_200ma"] = sp_200ma
                result["sp500_above_200ma"] = sp_price > sp_200ma
                result["sp500_pct_above_200ma"] = ((sp_price / sp_200ma) - 1) * 100
            else:
                result["sp500_above_200ma"] = None
        except Exception as e:
            logger.error(f"Failed to fetch S&P 500 data: {e}")
            result["sp500_above_200ma"] = None

        # Market regime: VIX + S&P position relative to 200MA
        vix = result.get("vix")
        sp_above = result.get("sp500_above_200ma")

        if vix and vix > 30:
            result["market_regime"] = "BEAR"
        elif sp_above is True and vix and vix < 20:
            result["market_regime"] = "BULL"
        elif sp_above is False:
            result["market_regime"] = "BEAR"
        else:
            result["market_regime"] = "SIDEWAYS"

        return result

    # --- Full stock analysis ---

    def get_stock_analysis(self, yf_ticker: str, finnhub_symbol: str | None = None) -> dict[str, Any]:
        """Get complete analysis for a stock: indicators + fundamentals + sentiment.

        Args:
            yf_ticker: Yahoo Finance ticker (e.g., "AAPL")
            finnhub_symbol: Finnhub symbol if different (e.g., "AAPL")
        """
        if finnhub_symbol is None:
            finnhub_symbol = yf_ticker

        result: dict[str, Any] = {"ticker": yf_ticker, "timestamp": datetime.utcnow().isoformat()}

        # OHLCV + Technical Indicators
        df = self.get_ohlcv(yf_ticker, period="1y")
        if not df.empty:
            result["indicators"] = calculate_indicators(df)

            # Relative strength vs S&P 500
            benchmark_df = self.get_benchmark_data()
            if not benchmark_df.empty:
                result["relative_strength_6m"] = calculate_relative_strength(df, benchmark_df)
        else:
            result["indicators"] = {"error": "No OHLCV data"}
            result["relative_strength_6m"] = None

        # Fundamentals
        result["fundamentals"] = get_fundamentals(yf_ticker)

        # Finnhub analyst data (recommendations + insider sentiment)
        try:
            result["analyst_data"] = self.finnhub.get_analyst_data(finnhub_symbol)
        except Exception as e:
            logger.error(f"Finnhub analyst data error for {finnhub_symbol}: {e}")
            result["analyst_data"] = {"error": str(e)}

        # Cache the data
        self._cache_market_data(yf_ticker, "full_analysis", result)

        return result

    # --- Universe management ---

    def get_universe(self) -> list[dict[str, Any]]:
        """Get the cached universe of instruments."""
        session = get_session()
        try:
            instruments = session.query(Instrument).order_by(
                Instrument.market_cap.desc()
            ).limit(200).all()
            return [
                {
                    "ticker": i.ticker,
                    "name": i.name,
                    "sector": i.sector,
                    "market_cap": i.market_cap,
                    "exchange": i.exchange,
                    "currency": i.currency,
                }
                for i in instruments
            ]
        finally:
            session.close()

    def refresh_universe(self, t212_instruments: list[dict[str, Any]]) -> int:
        """Refresh the instrument universe from T212 data + yfinance sector info.

        Args:
            t212_instruments: List of instruments from T212 API

        Returns:
            Number of instruments stored.
        """
        session = get_session()
        count = 0
        try:
            for inst in t212_instruments:
                ticker = inst.get("ticker", "")
                if not ticker:
                    continue

                existing = session.query(Instrument).filter_by(ticker=ticker).first()
                if existing:
                    existing.name = inst.get("name", existing.name)
                    existing.currency = inst.get("currencyCode", existing.currency)
                    existing.exchange = inst.get("exchange", existing.exchange)
                    existing.type = inst.get("type", existing.type)
                    existing.min_trade_quantity = inst.get("minTradeQuantity")
                    existing.max_open_quantity = inst.get("maxOpenQuantity")
                    existing.updated_at = datetime.utcnow()
                else:
                    session.add(Instrument(
                        ticker=ticker,
                        name=inst.get("name"),
                        currency=inst.get("currencyCode"),
                        exchange=inst.get("exchange"),
                        type=inst.get("type"),
                        min_trade_quantity=inst.get("minTradeQuantity"),
                        max_open_quantity=inst.get("maxOpenQuantity"),
                        updated_at=datetime.utcnow(),
                    ))
                count += 1

            session.commit()
            logger.info(f"Refreshed {count} instruments")
        except Exception as e:
            logger.error(f"Failed to refresh universe: {e}")
            session.rollback()
        finally:
            session.close()

        return count

    # --- Caching ---

    def _cache_market_data(self, ticker: str, data_type: str, data: dict[str, Any]) -> None:
        """Cache market data in SQLite."""
        session = get_session()
        try:
            session.add(MarketDataCache(
                ticker=ticker,
                data_type=data_type,
                timestamp=datetime.utcnow(),
                data_json=json.dumps(data, default=str),
                expires_at=datetime.utcnow() + timedelta(hours=12),
            ))
            session.commit()
        except Exception as e:
            logger.error(f"Failed to cache market data for {ticker}: {e}")
            session.rollback()
        finally:
            session.close()

    def get_cached_data(self, ticker: str, data_type: str) -> dict[str, Any] | None:
        """Retrieve cached market data if still valid."""
        session = get_session()
        try:
            entry = (
                session.query(MarketDataCache)
                .filter(
                    MarketDataCache.ticker == ticker,
                    MarketDataCache.data_type == data_type,
                    MarketDataCache.expires_at > datetime.utcnow(),
                )
                .order_by(MarketDataCache.timestamp.desc())
                .first()
            )
            if entry:
                return json.loads(entry.data_json)
            return None
        finally:
            session.close()

    def cache_news_sentiment(
        self,
        ticker: str | None,
        source: str,
        data_type: str,
        data: dict[str, Any],
        overall_score: float | None = None,
    ) -> None:
        """Cache news sentiment data."""
        session = get_session()
        try:
            session.add(NewsSentimentCache(
                ticker=ticker,
                source=source,
                data_type=data_type,
                timestamp=datetime.utcnow(),
                data_json=json.dumps(data, default=str),
                overall_score=overall_score,
                expires_at=datetime.utcnow() + timedelta(hours=6),
            ))
            session.commit()
        except Exception as e:
            logger.error(f"Failed to cache sentiment for {ticker}: {e}")
            session.rollback()
        finally:
            session.close()

    def close(self) -> None:
        """Close all API clients."""
        if self._finnhub:
            self._finnhub.close()
        if self._alpha_vantage:
            self._alpha_vantage.close()
