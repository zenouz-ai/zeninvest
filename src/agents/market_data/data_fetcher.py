"""Main data fetcher — orchestrates yfinance, Finnhub, Alpha Vantage, and T212."""

import json
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import pandas as pd
import yfinance as yf
from sqlalchemy import func

from src.agents.market_data.alpha_vantage_client import AlphaVantageClient
from src.agents.market_data.finnhub_client import FinnhubClient
from src.agents.market_data.fundamentals import get_fundamentals
from src.agents.market_data.macro_intelligence import get_latest_macro_state, get_macro_intelligence
from src.agents.market_data.indicators import calculate_indicators, calculate_relative_strength
from src.agents.market_data.seed_universe import get_seed_instruments
from src.agents.market_data.brave_enrichment import (
    SECTOR_ALIASES,
    extract_sector_market_cap_brave_answers,
)
from src.data.database import get_session
from src.data.models import Instrument, MarketDataCache, NewsSentimentCache, Order, StrategyDecision
from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.ticker_utils import t212_to_yf

logger = get_logger("data_fetcher")

# Dashboard event logger (fail-open import)
log_event: Callable[..., None] | None
try:
    from dashboard.backend.app.services.event_logger import log_event as _log_event
    log_event = _log_event
    DASHBOARD_AVAILABLE = True
except ImportError:
    DASHBOARD_AVAILABLE = False
    log_event = None


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

    def get_analyst_data_cached(self, yf_ticker: str) -> dict[str, Any]:
        """Get Finnhub analyst data with NewsSentimentCache lookup first."""
        cached = self.get_cached_news_sentiment(yf_ticker, "finnhub", "analyst_data")
        if cached:
            return cached
        try:
            data = self.finnhub.get_analyst_data(yf_ticker)
            self.cache_news_sentiment(
                ticker=yf_ticker,
                source="finnhub",
                data_type="analyst_data",
                data=data,
                ttl_hours=self.settings.cache_ttl_hours("finnhub_analyst"),
            )
            return data
        except Exception as e:
            logger.error(f"Finnhub analyst data error for {yf_ticker}: {e}")
            return {"error": str(e)}

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

        # Macro intelligence: sector trends + economic headlines (cached)
        macro_intel = self.get_macro_intelligence_cached()
        result["macro_intelligence"] = macro_intel

        # Proactive macro state (US-4.5 foundation): persisted daily scan injected
        # into cycle context when enabled. Existing macro_intelligence remains the
        # fallback if no proactive state exists yet.
        if self.settings.macro_proactive_scan_enabled:
            latest_macro_state = get_latest_macro_state()
            if latest_macro_state:
                result["macro_state"] = latest_macro_state

        return result

    def get_macro_intelligence_cached(self) -> dict[str, Any]:
        """Get sector performance and economic headlines, with cache lookup first."""
        if not self.settings.macro_intelligence_enabled:
            return {
                "enabled": False,
                "sector_trends": {},
                "economic_highlights": "",
                "sector_summary": "",
                "headlines": [],
            }

        cached = self.get_cached_news_sentiment(
            ticker=None, source="macro", data_type="macro_intelligence"
        )
        if cached:
            return cached

        try:
            macro_intel = get_macro_intelligence(
                self.alpha_vantage,
                self.finnhub,
                enabled=True,
            )
            if macro_intel.get("enabled"):
                self.cache_news_sentiment(
                    ticker=None,
                    source="macro",
                    data_type="macro_intelligence",
                    data=macro_intel,
                    ttl_hours=self.settings.cache_ttl_hours("macro_intelligence"),
                )
            return macro_intel
        except Exception as e:
            logger.warning(f"Macro intelligence fetch failed: {e}")
            return {
                "enabled": False,
                "sector_trends": {},
                "economic_highlights": "",
                "sector_summary": "",
                "headlines": [],
                "errors": [str(e)],
            }

    # --- Full stock analysis ---

    def get_stock_analysis_lite(self, yf_ticker: str) -> dict[str, Any]:
        """Get OHLCV + indicators + fundamentals only (no Finnhub).

        Used for screening and sub-strategy scoring. Tier 1 data only.
        Cached with configurable TTL (default 4h for intraday cycles).
        """
        cached = self.get_cached_data(yf_ticker, "lite_analysis")
        if cached:
            return cached

        result: dict[str, Any] = {
            "ticker": yf_ticker,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # OHLCV + Technical Indicators
        df = self.get_ohlcv(yf_ticker, period="1y")
        if not df.empty:
            result["indicators"] = calculate_indicators(
                df,
                volume_signals_enabled=self.settings.volume_signals_enabled,
            )
            benchmark_df = self.get_benchmark_data()
            if not benchmark_df.empty:
                result["relative_strength_6m"] = calculate_relative_strength(df, benchmark_df)
            else:
                result["relative_strength_6m"] = None
        else:
            result["indicators"] = {"error": "No OHLCV data"}
            result["relative_strength_6m"] = None

        # Fundamentals
        result["fundamentals"] = get_fundamentals(yf_ticker)

        self._cache_market_data(yf_ticker, "lite_analysis", result)
        return result

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
            result["indicators"] = calculate_indicators(
                df,
                volume_signals_enabled=self.settings.volume_signals_enabled,
            )

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

    def _cache_market_data(
        self,
        ticker: str,
        data_type: str,
        data: dict[str, Any],
        ttl_hours: int | None = None,
    ) -> None:
        """Cache market data in SQLite with configurable TTL."""
        if ttl_hours is None:
            ttl_hours = self.settings.cache_ttl_hours(data_type)
        session = get_session()
        try:
            session.add(MarketDataCache(
                ticker=ticker,
                data_type=data_type,
                timestamp=datetime.now(timezone.utc),
                data_json=json.dumps(data, default=str),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
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

    def get_cached_news_sentiment(
        self,
        ticker: str | None,
        source: str,
        data_type: str,
    ) -> dict[str, Any] | None:
        """Retrieve cached news sentiment if still valid."""
        session = get_session()
        try:
            q = session.query(NewsSentimentCache).filter(
                NewsSentimentCache.source == source,
                NewsSentimentCache.data_type == data_type,
                NewsSentimentCache.expires_at > datetime.now(timezone.utc),
            )
            if ticker is not None:
                q = q.filter(NewsSentimentCache.ticker == ticker)
            else:
                q = q.filter(NewsSentimentCache.ticker.is_(None))
            entry = q.order_by(NewsSentimentCache.timestamp.desc()).first()
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
        ttl_hours: int | None = None,
    ) -> None:
        """Cache news sentiment data with configurable TTL."""
        if ttl_hours is None:
            ttl_key = "finnhub_analyst" if source == "finnhub" else "alpha_vantage_ticker"
            ttl_hours = self.settings.cache_ttl_hours(ttl_key)
        session = get_session()
        try:
            session.add(NewsSentimentCache(
                ticker=ticker,
                source=source,
                data_type=data_type,
                timestamp=datetime.now(timezone.utc),
                data_json=json.dumps(data, default=str),
                overall_score=overall_score,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
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
        positions_count: int | None = None,
    ) -> list[dict[str, Any]]:
        """Screen the instrument universe for diverse candidates.

        Returns a sector-balanced, market-cap-tiered sample of stocks to
        evaluate.  Avoids re-analyzing tickers already in the portfolio or
        previously excluded.

        Args:
            exclude_tickers: Tickers to skip (e.g. current positions).
            max_candidates: Override for settings.max_candidates.
            positions_count: Number of portfolio holdings re-evaluated this cycle (for event metadata).

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
            # For intraday, use effective (capped at cycle_hours) so each cycle gets fresh pool
            cooldown_hours = getattr(
                settings, "effective_screening_cooldown_hours", None
            ) or settings.screening_cooldown_hours
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
                    # Exclude tickers flagged as unfetchable (delisted/invalid)
                    Instrument.data_available != False,  # noqa: E712
                    # Exclude recently screened stocks
                    (Instrument.last_screened_at.is_(None))
                    | (Instrument.last_screened_at < cooldown_cutoff),
                )
                .all()
            )

            if not instruments:
                # Fallback: grab whatever is available (seed if needed, or rotate when all in cooldown)
                eligible_total = (
                    session.query(Instrument)
                    .filter(
                        Instrument.sector.isnot(None),
                        Instrument.market_cap.isnot(None),
                        Instrument.market_cap > settings.small_cap_min,
                        Instrument.data_available != False,  # noqa: E712
                    )
                    .count()
                )
                logger.warning(
                    "No instruments past cooldown (cooldown=%dh). Eligible pool size: %d. Using fallback.",
                    cooldown_hours,
                    eligible_total,
                )
                return self._get_fallback_universe(exclude, total, session, cooldown_cutoff)

            # Last-investigated timestamp per ticker (max of StrategyDecision.timestamp)
            tickers = [inst.ticker for inst in instruments]
            last_inv_rows = (
                session.query(StrategyDecision.ticker, func.max(StrategyDecision.timestamp).label("last_ts"))
                .filter(StrategyDecision.ticker.in_(tickers))
                .group_by(StrategyDecision.ticker)
                .all()
            )
            last_investigated: dict[str, datetime] = {r.ticker: r.last_ts for r in last_inv_rows}

            # Review vs new: review = investigated 24-48h ago; new = never or >48h ago
            rw = getattr(settings, "review_window_hours", None) or [24, 48]
            try:
                min_h, max_h = int(rw[0]), int(rw[1])
            except (TypeError, IndexError, ValueError):
                min_h, max_h = 24, 48
            cutoff_newer = datetime.now(timezone.utc) - timedelta(hours=min_h)
            cutoff_older = datetime.now(timezone.utc) - timedelta(hours=max_h)

            def _is_review(t: str) -> bool:
                ts = last_investigated.get(t)
                if ts is None:
                    return False
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                return cutoff_older <= ts <= cutoff_newer

            # Bucket by market-cap tier and review/new status
            large_new: list[Instrument] = []
            large_review: list[Instrument] = []
            mid_new: list[Instrument] = []
            mid_review: list[Instrument] = []
            small_new: list[Instrument] = []
            small_review: list[Instrument] = []

            for inst in instruments:
                if inst.ticker in exclude:
                    continue
                cap = inst.market_cap or 0
                is_review = _is_review(inst.ticker)
                target_list = None
                if cap >= settings.large_cap_min:
                    target_list = large_review if is_review else large_new
                elif cap >= settings.mid_cap_min:
                    target_list = mid_review if is_review else mid_new
                else:
                    target_list = small_review if is_review else small_new
                target_list.append(inst)

            # Target counts per tier
            n_large = max(1, int(total * settings.large_cap_pct))
            n_mid = max(1, int(total * settings.mid_cap_pct))
            n_small = max(1, total - n_large - n_mid)

            # Within each tier, target share from "new" pool (uninvestigated_target_pct = new_share)
            try:
                new_share = max(0.0, min(1.0, float(getattr(settings, "uninvestigated_target_pct", 0.5))))
            except Exception:
                new_share = 0.5

            def _sample_tier(new_bucket: list[Instrument], review_bucket: list[Instrument], n: int) -> list[Instrument]:
                if n <= 0:
                    return []
                target_new = min(int(round(n * new_share)), len(new_bucket))
                selected: list[Instrument] = []
                if target_new > 0:
                    selected.extend(self._sector_balanced_sample(new_bucket, target_new, settings.candidates_per_sector))
                remaining = n - len(selected)
                if remaining > 0:
                    selected.extend(self._sector_balanced_sample(review_bucket, remaining, settings.candidates_per_sector))
                if len(selected) < n:
                    leftover_new = [i for i in new_bucket if i not in selected]
                    selected.extend(self._sector_balanced_sample(leftover_new, n - len(selected), settings.candidates_per_sector))
                return selected[:n]

            # Sample within each tier: 50% new, 50% review (sector-balanced)
            selected: list[Instrument] = []
            selected.extend(_sample_tier(large_new, large_review, n_large))
            selected.extend(_sample_tier(mid_new, mid_review, n_mid))
            selected.extend(_sample_tier(small_new, small_review, n_small))

            review_count = sum(1 for i in selected if _is_review(i.ticker))
            new_count = len(selected) - review_count

            logger.info(
                "Screened universe: %s candidates (large=%s, mid=%s, small=%s, cooldown=%sh, new_share=%.2f)",
                len(selected),
                n_large,
                n_mid,
                n_small,
                cooldown_hours,
                new_share,
            )

            candidates = [
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
            
            # Log universe_updated event
            if DASHBOARD_AVAILABLE and log_event is not None:
                try:
                    tickers_list = [c["ticker"] for c in candidates]
                    sector_counts = defaultdict(int)
                    for c in candidates:
                        sector_counts[c.get("sector", "Unknown")] += 1
                    
                    large_count = len(large_new) + len(large_review)
                    mid_count = len(mid_new) + len(mid_review)
                    small_count = len(small_new) + len(small_review)
                    total_available = large_count + mid_count + small_count
                    screened_large = min(n_large, large_count)
                    screened_mid = min(n_mid, mid_count)
                    screened_small = min(n_small, small_count)
                    msg = f"Screened {len(candidates)}/{total_available} candidates (large={screened_large}/{large_count}, mid={screened_mid}/{mid_count}, small={screened_small}/{small_count}) — reviews: {review_count}, new: {new_count}"
                    if positions_count is not None:
                        msg += f" | {positions_count} in portfolio"
                    # Cumulative stats (lifetime)
                    cumul_screened = session.query(Instrument).filter(Instrument.last_screened_at.isnot(None)).count()
                    cumul_reviewed = session.query(func.count(func.distinct(StrategyDecision.ticker))).scalar() or 0
                    cumul_orders = session.query(Order).count()
                    msg += f" | cumul: {cumul_screened} screened, {cumul_reviewed} reviewed, {cumul_orders} orders"
                    meta: dict[str, Any] = {
                        "num_candidates": len(candidates),
                        "total_available": total_available,
                        "tickers": tickers_list[:50],  # Limit to first 50 for storage
                        "sector_distribution": dict(sector_counts),
                        "large_cap_count": screened_large,
                        "mid_cap_count": screened_mid,
                        "small_cap_count": screened_small,
                        "large_pool": large_count,
                        "mid_pool": mid_count,
                        "small_pool": small_count,
                        "cooldown_hours": cooldown_hours,
                        "review_count": review_count,
                        "new_count": new_count,
                    }
                    if positions_count is not None:
                        meta["positions_count"] = positions_count
                    meta["cumul_screened"] = cumul_screened
                    meta["cumul_reviewed"] = cumul_reviewed
                    meta["cumul_orders"] = cumul_orders
                    log_event(
                        event_type="universe_updated",
                        source="screener",
                        message=msg,
                        metadata=meta,
                    )
                except Exception:
                    pass  # Fail-open
            
            return candidates

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
        cooldown_cutoff: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fallback using curated seed universe of well-known stocks.

        When instruments table lacks sector/market_cap data (e.g. first run
        before enrichment), use the curated seed list of known-good US equities
        instead of random T212 picks that often include delisted/unfetchable tickers.
        Seeds are upserted into the instruments table so they persist.

        When all enriched instruments are in cooldown (pool exhausted), orders by
        last_screened_at ASC (oldest first) to rotate through the pool instead of
        returning the same top 30 by market cap every cycle.

        Proactive seed: when eligible pool is below 2*max_candidates, merge seed
        instruments to ensure rotation has enough headroom.
        """
        settings = self.settings
        min_pool_threshold = 2 * total  # Need 2x headroom for rotation

        eligible_count = (
            session.query(Instrument)
            .filter(
                Instrument.sector.isnot(None),
                Instrument.market_cap.isnot(None),
                Instrument.market_cap > settings.small_cap_min,
                Instrument.data_available != False,  # noqa: E712
            )
            .count()
        )

        if eligible_count < min_pool_threshold:
            seed_stocks = get_seed_instruments()
            # Only merge seed instruments that exist in the instruments table (i.e. from T212).
            # Never add new instruments from seed — ensures all screened tickers are tradeable on T212.
            db_tickers = {r[0] for r in session.query(Instrument.ticker).all()}
            matched = 0
            for seed in seed_stocks:
                if seed["ticker"] not in db_tickers:
                    continue
                existing = session.query(Instrument).filter_by(ticker=seed["ticker"]).first()
                if existing:
                    if not existing.sector or existing.sector == "Unknown":
                        existing.sector = seed["sector"]
                    if not existing.market_cap:
                        existing.market_cap = seed["market_cap"]
                    if not existing.name:
                        existing.name = seed["name"]
                    matched += 1
            if matched > 0:
                session.commit()
            logger.info(
                "Pool below threshold (%d < %d): enriched %d of %d seed instruments (only T212-available)",
                eligible_count,
                min_pool_threshold,
                matched,
                len(seed_stocks),
            )

        # Reuse settings for filters below
        settings = self.settings

        # First try: same cooldown logic as main path
        if cooldown_cutoff is not None:
            instruments = (
                session.query(Instrument)
                .filter(
                    Instrument.sector.isnot(None),
                    Instrument.sector != "",
                    Instrument.sector != "Unknown",
                    Instrument.market_cap.isnot(None),
                    Instrument.market_cap > settings.small_cap_min,
                    Instrument.data_available != False,  # noqa: E712
                    (Instrument.last_screened_at.is_(None))
                    | (Instrument.last_screened_at < cooldown_cutoff),
                )
                .all()
            )
            if instruments:
                # Apply exclude and sector-balanced sample; use review/new bucketing same as main path
                tickers = [inst.ticker for inst in instruments]
                last_inv_rows = (
                    session.query(StrategyDecision.ticker, func.max(StrategyDecision.timestamp).label("last_ts"))
                    .filter(StrategyDecision.ticker.in_(tickers))
                    .group_by(StrategyDecision.ticker)
                    .all()
                )
                last_inv = {r.ticker: r.last_ts for r in last_inv_rows}
                rw = getattr(settings, "review_window_hours", None) or [24, 48]
                try:
                    min_h, max_h = int(rw[0]), int(rw[1])
                except (TypeError, IndexError, ValueError):
                    min_h, max_h = 24, 48
                cutoff_newer = datetime.now(timezone.utc) - timedelta(hours=min_h)
                cutoff_older = datetime.now(timezone.utc) - timedelta(hours=max_h)

                def _is_review(t: str) -> bool:
                    ts = last_inv.get(t)
                    if ts is None:
                        return False
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    return cutoff_older <= ts <= cutoff_newer

                large_new, large_review = [], []
                mid_new, mid_review = [], []
                small_new, small_review = [], []
                for inst in instruments:
                    if inst.ticker in exclude:
                        continue
                    cap = inst.market_cap or 0
                    is_rev = _is_review(inst.ticker)
                    if cap >= settings.large_cap_min:
                        (large_review if is_rev else large_new).append(inst)
                    elif cap >= settings.mid_cap_min:
                        (mid_review if is_rev else mid_new).append(inst)
                    else:
                        (small_review if is_rev else small_new).append(inst)
                try:
                    new_share = max(0.0, min(1.0, float(getattr(settings, "uninvestigated_target_pct", 0.5))))
                except Exception:
                    new_share = 0.5
                n_large = max(1, int(total * settings.large_cap_pct))
                n_mid = max(1, int(total * settings.mid_cap_pct))
                n_small = max(1, total - n_large - n_mid)

                def _sample_tier(nb, rb, n):
                    if n <= 0:
                        return []
                    tf = min(int(round(n * new_share)), len(nb))
                    sel = []
                    if tf > 0:
                        sel.extend(self._sector_balanced_sample(nb, tf, settings.candidates_per_sector))
                    rem = n - len(sel)
                    if rem > 0:
                        sel.extend(self._sector_balanced_sample(rb, rem, settings.candidates_per_sector))
                    if len(sel) < n:
                        leftover = [i for i in nb if i not in sel]
                        sel.extend(self._sector_balanced_sample(leftover, n - len(sel), settings.candidates_per_sector))
                    return sel[:n]

                selected = []
                selected.extend(_sample_tier(large_new, large_review, n_large))
                selected.extend(_sample_tier(mid_new, mid_review, n_mid))
                selected.extend(_sample_tier(small_new, small_review, n_small))
                return [
                    {"ticker": i.ticker, "name": i.name, "sector": i.sector or "Unknown", "market_cap": i.market_cap, "exchange": i.exchange, "currency": i.currency}
                    for i in selected
                ]

        # All in cooldown: order by last_screened_at ASC (oldest first) to rotate pool
        instruments = (
            session.query(Instrument)
            .filter(
                Instrument.sector.isnot(None),
                Instrument.market_cap.isnot(None),
                Instrument.market_cap > settings.small_cap_min,
                Instrument.data_available != False,  # noqa: E712
            )
            .order_by(Instrument.last_screened_at.asc().nulls_first(), Instrument.market_cap.desc())
            .all()
        )
        result = [
            {"ticker": i.ticker, "name": i.name, "sector": i.sector or "Unknown", "market_cap": i.market_cap, "exchange": i.exchange, "currency": i.currency}
            for i in instruments
            if i.ticker not in exclude
        ]
        logger.info(
            "Pool exhausted: using least-recently-screened rotation. Returning %d candidates (pool had %d eligible, excluded %d)",
            len(result[:total]),
            len(instruments),
            len(exclude),
        )
        return result[:total]

    def enrich_instrument_metadata(self, ticker: str, fundamentals: dict[str, Any]) -> None:
        """Back-fill sector, market_cap, industry, and business_summary from yfinance data."""
        sector = fundamentals.get("sector")
        market_cap = fundamentals.get("market_cap")
        industry = fundamentals.get("industry")
        business_summary = fundamentals.get("business_summary")
        if not sector and not market_cap and not business_summary:
            return

        session = get_session()
        try:
            inst = session.query(Instrument).filter_by(ticker=ticker).first()
            if inst:
                if sector and sector != "Unknown" and inst.sector != sector:
                    inst.sector = sector
                if market_cap and (inst.market_cap is None or inst.market_cap == 0):
                    inst.market_cap = market_cap
                if industry and not inst.industry:
                    inst.industry = industry
                if business_summary and not inst.business_summary:
                    inst.business_summary = business_summary
                inst.updated_at = datetime.now(timezone.utc)
                session.commit()
        except Exception as e:
            logger.error(f"Failed to enrich instrument {ticker}: {e}")
            session.rollback()
        finally:
            session.close()

    def _normalize_sector(self, raw: str | None) -> str | None:
        """Map raw sector/industry string to standard sector name."""
        if not raw or not str(raw).strip():
            return None
        low = str(raw).strip().lower()
        return SECTOR_ALIASES.get(low, raw.strip())

    def enrich_instruments_batch(self, max_per_run: int | None = None) -> int:
        """Enrich instruments missing sector/market_cap via cascade: yfinance → Finnhub → AV → BRAVE_ANSWERS.

        Queries instruments where sector or market_cap is null/empty, enriches up to max_per_run.
        Sources tried in order: yfinance (fastest, free), Finnhub, Alpha Vantage, BRAVE_ANSWERS.

        Returns:
            Number of instruments successfully enriched.
        """
        settings = self.settings
        limit = max_per_run or settings.batch_enrichment_per_run
        session = get_session()
        try:
            candidates = (
                session.query(Instrument)
                .filter(
                    Instrument.data_available != False,  # noqa: E712
                    (
                        (Instrument.sector.is_(None))
                        | (Instrument.sector == "")
                        | (Instrument.sector == "Unknown")
                        | (Instrument.market_cap.is_(None))
                        | (Instrument.market_cap == 0),
                    ),
                )
                .limit(limit)
                .all()
            )
            if not candidates:
                logger.info("No instruments need batch enrichment")
                return 0

            enriched = 0
            for inst in candidates:
                yf_symbol = t212_to_yf(inst.ticker)
                sector = None
                market_cap = None
                industry = None
                business_summary = None

                # 1. yfinance (fastest, free, high accuracy for US)
                try:
                    fund = get_fundamentals(yf_symbol)
                    if "error" not in fund:
                        s = fund.get("sector")
                        if s and s != "Unknown":
                            sector = self._normalize_sector(s)
                        mc = fund.get("market_cap")
                        if mc and float(mc or 0) > 0:
                            market_cap = int(float(mc))
                        ind = fund.get("industry")
                        if ind and str(ind).strip():
                            industry = str(ind).strip()
                        bs = fund.get("business_summary")
                        if bs and str(bs).strip():
                            business_summary = str(bs).strip()
                except Exception as e:
                    logger.debug(f"yfinance fundamentals failed for {inst.ticker}: {e}")

                # 2. Finnhub
                if not sector or not market_cap:
                    try:
                        profile = self.finnhub.get_company_profile(yf_symbol)
                        ind = profile.get("finnhubIndustry")
                        cap = profile.get("marketCapitalization")
                        if ind and not sector:
                            sector = self._normalize_sector(ind)
                        if cap and cap > 0 and not market_cap:
                            market_cap = cap
                    except Exception as e:
                        logger.debug(f"Finnhub profile failed for {inst.ticker}: {e}")

                # 3. Alpha Vantage (25/day shared)
                if not sector or not market_cap:
                    try:
                        ov = self.alpha_vantage.get_company_overview(yf_symbol)
                        if ov.get("Sector") and not sector:
                            sector = self._normalize_sector(ov["Sector"])
                        if ov.get("MarketCapitalization") and not market_cap:
                            market_cap = ov["MarketCapitalization"]
                    except Exception as e:
                        logger.debug(f"Alpha Vantage OVERVIEW failed for {inst.ticker}: {e}")

                # 4. BRAVE_ANSWERS (last resort, 2k/month)
                if not sector or not market_cap:
                    try:
                        result = extract_sector_market_cap_brave_answers(inst.ticker)
                        if result.get("sector") and not sector:
                            sector = self._normalize_sector(result["sector"])
                        if result.get("market_cap") and not market_cap:
                            market_cap = result["market_cap"]
                    except Exception as e:
                        logger.debug(f"Brave Answers enrichment failed for {inst.ticker}: {e}")

                if sector or market_cap or industry or business_summary:
                    if sector and (not inst.sector or inst.sector == "Unknown"):
                        inst.sector = sector
                    if market_cap and (not inst.market_cap or inst.market_cap == 0):
                        inst.market_cap = market_cap
                    if industry and not inst.industry:
                        inst.industry = industry
                    if business_summary and not inst.business_summary:
                        inst.business_summary = business_summary
                    inst.updated_at = datetime.now(timezone.utc)
                    enriched += 1
                    logger.debug(
                        f"Enriched {inst.ticker}: sector={sector}, market_cap={market_cap}, industry={bool(industry)}, summary={bool(business_summary)}"
                    )

            session.commit()
            logger.info(f"Batch enrichment: {enriched}/{len(candidates)} instruments updated")
            return enriched
        except Exception as e:
            logger.error(f"Batch enrichment failed: {e}")
            session.rollback()
            return 0
        finally:
            session.close()

    def mark_instrument_unavailable(self, ticker: str) -> None:
        """Flag an instrument as data_available=False so it's excluded from future screens."""
        session = get_session()
        try:
            inst = session.query(Instrument).filter_by(ticker=ticker).first()
            if inst:
                inst.data_available = False
                inst.updated_at = datetime.now(timezone.utc)
                session.commit()
                logger.info(f"Marked {ticker} as unavailable (no OHLCV data)")
        except Exception as e:
            logger.error(f"Failed to mark {ticker} unavailable: {e}")
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
