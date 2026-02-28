"""Main data fetcher — orchestrates yfinance, Finnhub, Alpha Vantage, and T212."""

import json
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import yfinance as yf
from sqlalchemy import func

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

        result: dict[str, Any] = {"ticker": yf_ticker, "timestamp": datetime.now(timezone.utc).isoformat()}

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
                    existing.updated_at = datetime.now(timezone.utc)
                else:
                    session.add(Instrument(
                        ticker=ticker,
                        name=inst.get("name"),
                        currency=inst.get("currencyCode"),
                        exchange=inst.get("exchange"),
                        type=inst.get("type"),
                        min_trade_quantity=inst.get("minTradeQuantity"),
                        max_open_quantity=inst.get("maxOpenQuantity"),
                        updated_at=datetime.now(timezone.utc),
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
                timestamp=datetime.now(timezone.utc),
                data_json=json.dumps(data, default=str),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
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
                    MarketDataCache.expires_at > datetime.now(timezone.utc),
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
                timestamp=datetime.now(timezone.utc),
                data_json=json.dumps(data, default=str),
                overall_score=overall_score,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=6),
            ))
            session.commit()
        except Exception as e:
            logger.error(f"Failed to cache sentiment for {ticker}: {e}")
            session.rollback()
        finally:
            session.close()

    # --- Universe screening ---

    def get_screened_universe(
        self,
        exclude_tickers: set[str] | None = None,
        max_candidates: int | None = None,
    ) -> list[dict[str, Any]]:
        """Screen the instrument universe for diverse candidates.

        Returns a sector-balanced, market-cap-tiered sample of stocks to
        evaluate.  Avoids re-analyzing tickers already in the portfolio or
        previously excluded.

        Args:
            exclude_tickers: Tickers to skip (e.g. current positions).
            max_candidates: Override for settings.max_candidates.

        Returns:
            List of candidate dicts with keys: ticker, name, sector,
            market_cap, exchange, currency.
        """
        settings = self.settings
        exclude = exclude_tickers or set()
        total = max_candidates or settings.max_candidates
        session = get_session()

        try:
            # Cooldown cutoff: exclude instruments screened within the window
            cooldown_hours = settings.screening_cooldown_hours
            cooldown_cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)

            # Query all instruments that have sector + market_cap populated
            instruments = (
                session.query(Instrument)
                .filter(
                    Instrument.sector.isnot(None),
                    Instrument.sector != "",
                    Instrument.sector != "Unknown",
                    Instrument.market_cap.isnot(None),
                    Instrument.market_cap > settings.small_cap_min,
                    # Exclude recently screened stocks
                    (Instrument.last_screened_at.is_(None))
                    | (Instrument.last_screened_at < cooldown_cutoff),
                )
                .all()
            )

            if not instruments:
                # Fallback: grab whatever is available
                logger.warning("No instruments with sector/market_cap. Using raw universe.")
                return self._get_fallback_universe(exclude, total, session)

            # Bucket by market-cap tier
            large: list[Instrument] = []
            mid: list[Instrument] = []
            small: list[Instrument] = []

            for inst in instruments:
                if inst.ticker in exclude:
                    continue
                cap = inst.market_cap or 0
                if cap >= settings.large_cap_min:
                    large.append(inst)
                elif cap >= settings.mid_cap_min:
                    mid.append(inst)
                else:
                    small.append(inst)

            # Target counts per tier
            n_large = max(1, int(total * settings.large_cap_pct))
            n_mid = max(1, int(total * settings.mid_cap_pct))
            n_small = max(1, total - n_large - n_mid)

            # Sample within each tier using sector-balanced selection
            selected: list[Instrument] = []
            selected.extend(self._sector_balanced_sample(large, n_large, settings.candidates_per_sector))
            selected.extend(self._sector_balanced_sample(mid, n_mid, settings.candidates_per_sector))
            selected.extend(self._sector_balanced_sample(small, n_small, settings.candidates_per_sector))

            logger.info(
                f"Screened universe: {len(selected)} candidates "
                f"(large={min(n_large, len(large))}, "
                f"mid={min(n_mid, len(mid))}, "
                f"small={min(n_small, len(small))}, "
                f"cooldown={cooldown_hours}h)"
            )

            return [
                {
                    "ticker": i.ticker,
                    "name": i.name,
                    "sector": i.sector,
                    "market_cap": i.market_cap,
                    "exchange": i.exchange,
                    "currency": i.currency,
                }
                for i in selected
            ]

        finally:
            session.close()

    @staticmethod
    def _sector_balanced_sample(
        instruments: list,
        n: int,
        per_sector: int,
    ) -> list:
        """Sample n instruments ensuring at least per_sector from each sector."""
        if not instruments:
            return []

        by_sector: dict[str, list] = defaultdict(list)
        for inst in instruments:
            by_sector[inst.sector or "Unknown"].append(inst)

        selected: list = []
        sectors = list(by_sector.keys())
        random.shuffle(sectors)

        # Round 1: guarantee per_sector from each sector
        for sector in sectors:
            pool = by_sector[sector]
            random.shuffle(pool)
            take = min(per_sector, len(pool))
            selected.extend(pool[:take])
            by_sector[sector] = pool[take:]

        # Round 2: fill remaining slots from all sectors
        remaining = n - len(selected)
        if remaining > 0:
            leftover = [inst for pool in by_sector.values() for inst in pool]
            random.shuffle(leftover)
            selected.extend(leftover[:remaining])

        return selected[:n]

    def _get_fallback_universe(
        self,
        exclude: set[str],
        total: int,
        session: Any,
    ) -> list[dict[str, Any]]:
        """Fallback when instruments lack sector/market_cap data."""
        instruments = (
            session.query(Instrument)
            .filter(Instrument.ticker.notin_(exclude) if exclude else True)
            .order_by(func.random())
            .limit(total)
            .all()
        )
        return [
            {
                "ticker": i.ticker,
                "name": i.name,
                "sector": i.sector or "Unknown",
                "market_cap": i.market_cap,
                "exchange": i.exchange,
                "currency": i.currency,
            }
            for i in instruments
        ]

    def enrich_instrument_metadata(self, ticker: str, fundamentals: dict[str, Any]) -> None:
        """Back-fill sector and market_cap into the instruments table from yfinance data."""
        sector = fundamentals.get("sector")
        market_cap = fundamentals.get("market_cap")
        if not sector and not market_cap:
            return

        session = get_session()
        try:
            inst = session.query(Instrument).filter_by(ticker=ticker).first()
            if inst:
                if sector and sector != "Unknown" and inst.sector != sector:
                    inst.sector = sector
                if market_cap and (inst.market_cap is None or inst.market_cap == 0):
                    inst.market_cap = market_cap
                inst.updated_at = datetime.now(timezone.utc)
                session.commit()
        except Exception as e:
            logger.error(f"Failed to enrich instrument {ticker}: {e}")
            session.rollback()
        finally:
            session.close()

    def mark_instruments_screened(self, tickers: list[str]) -> None:
        """Stamp last_screened_at on instruments so they enter the cooldown window."""
        if not tickers:
            return
        session = get_session()
        try:
            now = datetime.now(timezone.utc)
            session.query(Instrument).filter(
                Instrument.ticker.in_(tickers),
            ).update(
                {Instrument.last_screened_at: now},
                synchronize_session="fetch",
            )
            session.commit()
            logger.info(f"Marked {len(tickers)} instruments as screened (cooldown starts now).")
        except Exception as e:
            logger.error(f"Failed to mark instruments screened: {e}")
            session.rollback()
        finally:
            session.close()

    # --- Per-ticker news extraction ---

    @staticmethod
    def extract_per_ticker_news(
        av_articles: list[dict[str, Any]],
        tickers: list[str],
    ) -> dict[str, str]:
        """Extract per-ticker news summaries from Alpha Vantage articles.

        Parses each article's ticker_sentiments array to find articles relevant
        to each ticker, then builds a compact text summary per ticker.

        Args:
            av_articles: List of processed article dicts from Alpha Vantage.
            tickers: List of yfinance-style ticker symbols to match.

        Returns:
            Dict mapping ticker -> formatted news summary string.
        """
        ticker_articles: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for article in av_articles:
            for ts in article.get("ticker_sentiments", []):
                av_ticker = ts.get("ticker", "")
                # Alpha Vantage uses bare ticker symbols (AAPL, MSFT)
                for t in tickers:
                    if av_ticker == t or av_ticker in t:
                        ticker_articles[t].append({
                            "title": article.get("title", ""),
                            "source": article.get("source", ""),
                            "overall_sentiment_score": article.get("overall_sentiment_score", 0),
                            "overall_sentiment_label": article.get("overall_sentiment_label", "Neutral"),
                            "ticker_sentiment_score": ts.get("sentiment_score", 0),
                            "ticker_relevance": ts.get("relevance_score", 0),
                        })
                        break

        result: dict[str, str] = {}
        for ticker in tickers:
            articles = ticker_articles.get(ticker, [])
            if not articles:
                result[ticker] = ""
                continue

            # Sort by relevance, take top 5
            articles.sort(key=lambda a: a.get("ticker_relevance", 0), reverse=True)
            top = articles[:5]

            lines = []
            scores = [a["ticker_sentiment_score"] for a in top]
            avg_score = sum(scores) / len(scores) if scores else 0
            bullish = sum(1 for s in scores if s > 0.15)
            bearish = sum(1 for s in scores if s < -0.15)
            lines.append(f"Ticker avg sentiment: {avg_score:+.3f} "
                         f"(Bullish: {bullish}, Bearish: {bearish}, Articles: {len(articles)})")

            for a in top:
                score = a["overall_sentiment_score"]
                label = a["overall_sentiment_label"]
                title = a["title"][:80]
                source = a["source"]
                lines.append(f"  [{label} {score:+.3f}] {title} ({source})")

            result[ticker] = "\n".join(lines)

        return result

    def close(self) -> None:
        """Close all API clients."""
        if self._finnhub:
            self._finnhub.close()
        if self._alpha_vantage:
            self._alpha_vantage.close()
