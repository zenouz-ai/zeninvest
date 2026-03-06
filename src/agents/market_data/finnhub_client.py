"""Finnhub API client for news sentiment, analyst data, and insider info."""

import time
from datetime import datetime, timezone
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.data.database import get_session
from src.data.models import ApiLog
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("finnhub_client")

# Rate limit: 60 requests/min for free tier
_last_request_time: float = 0.0
_MIN_REQUEST_INTERVAL = 1.1  # ~55 req/min to stay safe


class FinnhubClient:
    """Client for Finnhub.io API."""

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.finnhub_base_url.rstrip("/")
        self.api_key = settings.finnhub_api_key
        self._client = httpx.Client(timeout=15.0)

    def _throttle(self) -> None:
        """Enforce rate limit."""
        global _last_request_time
        elapsed = time.monotonic() - _last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        _last_request_time = time.monotonic()

    def _log_api_call(
        self,
        endpoint: str,
        status_code: int | None,
        response_body: str | None,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        session = get_session()
        try:
            session.add(ApiLog(
                timestamp=datetime.now(timezone.utc),
                service="finnhub",
                method="GET",
                endpoint=endpoint,
                status_code=status_code,
                response_body=response_body[:3000] if response_body else None,
                duration_ms=duration_ms,
                error=error,
            ))
            session.commit()
        except Exception as e:
            logger.error(f"Failed to log Finnhub API call: {e}")
            session.rollback()
        finally:
            session.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception(lambda e: not (
            isinstance(e, httpx.HTTPStatusError) and 400 <= e.response.status_code < 500
        )),
    )
    def _request(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Make an authenticated GET request to Finnhub.

        Retries on 5xx/network errors only. 4xx errors (e.g. 403 Forbidden
        for premium-only endpoints) are raised immediately without retrying.
        """
        self._throttle()
        url = f"{self.base_url}{endpoint}"
        all_params = {"token": self.api_key}
        if params:
            all_params.update(params)

        start = time.monotonic()
        error_msg = None
        status_code = None
        response_text = None

        try:
            response = self._client.get(url, params=all_params)
            status_code = response.status_code
            response_text = response.text
            response.raise_for_status()
            return response.json()
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Finnhub API error on {endpoint}: {error_msg}")
            raise
        finally:
            duration = (time.monotonic() - start) * 1000
            self._log_api_call(endpoint, status_code, response_text, duration, error_msg)

    def get_analyst_recommendations(self, symbol: str) -> dict[str, Any]:
        """Get analyst buy/hold/sell consensus.

        If the endpoint is unavailable, returns placeholder data with
        unavailable=True.
        """
        try:
            data = self._request("/stock/recommendation", {"symbol": symbol})
            if not data or not isinstance(data, list) or len(data) == 0:
                return {
                    "symbol": symbol,
                    "unavailable": True,
                    "reason": "No analyst data returned by API",
                    "strong_buy": 0, "buy": 0, "hold": 0, "sell": 0, "strong_sell": 0,
                    "total_analysts": 0,
                    "consensus": "N/A",
                }

            latest = data[0]
            total = (
                latest.get("buy", 0) + latest.get("hold", 0) +
                latest.get("sell", 0) + latest.get("strongBuy", 0) +
                latest.get("strongSell", 0)
            )

            return {
                "symbol": symbol,
                "unavailable": False,
                "period": latest.get("period"),
                "strong_buy": latest.get("strongBuy", 0),
                "buy": latest.get("buy", 0),
                "hold": latest.get("hold", 0),
                "sell": latest.get("sell", 0),
                "strong_sell": latest.get("strongSell", 0),
                "total_analysts": total,
                "consensus": _determine_consensus(latest),
            }
        except Exception as e:
            logger.warning(f"Analyst recommendations unavailable for {symbol}: {e}")
            return {
                "symbol": symbol,
                "unavailable": True,
                "reason": str(e),
                "strong_buy": 0, "buy": 0, "hold": 0, "sell": 0, "strong_sell": 0,
                "total_analysts": 0,
                "consensus": "N/A",
            }

    def get_insider_sentiment(self, symbol: str) -> dict[str, Any]:
        """Get insider sentiment MSPR score (-100 to +100).

        If the endpoint is unavailable, returns placeholder data with
        unavailable=True.
        """
        try:
            data = self._request("/stock/insider-sentiment", {"symbol": symbol, "from": "2024-01-01"})
            if not data or "data" not in data or len(data["data"]) == 0:
                return {
                    "symbol": symbol,
                    "unavailable": True,
                    "reason": "No insider data returned by API",
                    "mspr": 0,
                    "change": 0,
                    "month": None,
                    "year": None,
                }

            # Get the most recent month
            latest = data["data"][-1]
            return {
                "symbol": symbol,
                "unavailable": False,
                "mspr": latest.get("mspr", 0),
                "change": latest.get("change", 0),
                "month": latest.get("month"),
                "year": latest.get("year"),
            }
        except Exception as e:
            logger.warning(f"Insider sentiment unavailable for {symbol}: {e}")
            return {
                "symbol": symbol,
                "unavailable": True,
                "reason": str(e),
                "mspr": 0,
                "change": 0,
                "month": None,
                "year": None,
            }

    def get_analyst_data(self, symbol: str) -> dict[str, Any]:
        """Get analyst recommendations and insider sentiment for a stock.

        Note: Finnhub news-sentiment and price-target endpoints are
        premium-only (403 on free tier). News sentiment is sourced from
        Alpha Vantage instead. Price targets are on the future roadmap.
        """
        return {
            "analyst_recommendations": self.get_analyst_recommendations(symbol),
            "insider_sentiment": self.get_insider_sentiment(symbol),
        }

    def get_market_news(self, category: str = "general") -> list[dict[str, Any]]:
        """Get general market news (free tier).

        Args:
            category: 'general' for broad market news (Fed, tariffs, earnings, etc.)

        Returns:
            List of article dicts with headline, summary, source, url, datetime.
        """
        try:
            data = self._request("/news", {"category": category})
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"Finnhub market news unavailable: {e}")
            return []

    def close(self) -> None:
        self._client.close()


def _determine_consensus(rec: dict[str, Any]) -> str:
    """Determine consensus from analyst recommendation counts."""
    buy_side = rec.get("strongBuy", 0) + rec.get("buy", 0)
    sell_side = rec.get("strongSell", 0) + rec.get("sell", 0)
    hold = rec.get("hold", 0)

    if buy_side > sell_side + hold:
        return "BUY"
    elif sell_side > buy_side + hold:
        return "SELL"
    else:
        return "HOLD"
