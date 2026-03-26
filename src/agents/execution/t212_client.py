"""Trading 212 API client for Practice/Demo mode."""

import base64
import json
import math
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.data.database import get_session
from src.data.models import ApiLog
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("t212_client")

# T212 API expects "DAY" or "GOOD_TILL_CANCEL"; we accept "GTC" from config/callers.
T212_TIME_VALIDITY: dict[str, str] = {"GTC": "GOOD_TILL_CANCEL", "DAY": "DAY"}


def _t212_time_validity(value: str) -> str:
    """Map config/caller time validity to T212 API enum."""
    return T212_TIME_VALIDITY.get(value.upper(), value)


def _is_retryable(exc: BaseException) -> bool:
    """Only retry on transient errors: 429, 5xx, and network failures."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return isinstance(exc, (httpx.RequestError, json.JSONDecodeError))


class T212Client:
    """Client for Trading 212 Invest API (Practice/Demo mode)."""

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.t212_base_url.rstrip("/")
        api_key = settings.t212_api_key
        api_secret = settings.t212_api_secret
        credentials = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
        self._headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        }
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=self._headers,
            timeout=30.0,
        )
        self._rate_remaining: int | None = None

    def _check_rate_limit(self) -> None:
        """Pause if rate limit is getting low."""
        if self._rate_remaining is not None and self._rate_remaining < 5:
            logger.warning(f"Rate limit low ({self._rate_remaining} remaining), pausing 2s")
            time.sleep(2)

    def _log_api_call(
        self,
        method: str,
        endpoint: str,
        status_code: int | None,
        request_body: str | None,
        response_body: str | None,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        """Log API call to database."""
        session = get_session()
        try:
            session.add(ApiLog(
                timestamp=datetime.now(timezone.utc),
                service="t212",
                method=method,
                endpoint=endpoint,
                status_code=status_code,
                request_body=request_body,
                response_body=response_body[:5000] if response_body else None,
                duration_ms=duration_ms,
                error=error,
            ))
            session.commit()
        except Exception as e:
            logger.error(f"Failed to log API call: {e}")
            session.rollback()
        finally:
            session.close()

    def _request(
        self,
        method: str,
        endpoint: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        *,
        ignore_404: bool = False,
    ) -> dict[str, Any] | list[Any]:
        """Make an authenticated API request.

        GET requests are retried (safe/idempotent). POST and DELETE requests
        are NOT retried to prevent duplicate orders or double-cancellations
        (T212 has no idempotency keys). See audit finding C-1.
        """
        is_safe = method.upper() in ("GET", "HEAD", "OPTIONS")
        if is_safe:
            return self._request_with_retry(
                method, endpoint, json_body=json_body, params=params, ignore_404=ignore_404,
            )
        return self._request_once(
            method, endpoint, json_body=json_body, params=params, ignore_404=ignore_404,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
    def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        *,
        ignore_404: bool = False,
    ) -> dict[str, Any] | list[Any]:
        """Retryable request — only for safe/idempotent methods (GET)."""
        return self._request_once(
            method, endpoint, json_body=json_body, params=params, ignore_404=ignore_404,
        )

    def _request_once(
        self,
        method: str,
        endpoint: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        *,
        ignore_404: bool = False,
    ) -> dict[str, Any] | list[Any]:
        """Execute a single HTTP request without automatic retry."""
        self._check_rate_limit()

        start = time.monotonic()
        error_msg = None
        status_code = None
        response_text = None

        try:
            response = self._client.request(
                method=method,
                url=endpoint,
                json=json_body,
                params=params,
            )
            status_code = response.status_code
            response_text = response.text

            # Track rate limit
            remaining = response.headers.get("x-ratelimit-remaining")
            if remaining is not None:
                self._rate_remaining = int(remaining)

            # 404 "no position" is expected when querying a ticker not held — don't retry
            if status_code == 404 and ignore_404:
                return {}

            response.raise_for_status()
            # T212 DELETE endpoints return 200 with empty body
            if not response.text or not response.text.strip():
                return {}
            return response.json()

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            logger.error(f"T212 API error on {method} {endpoint}: {error_msg}")
            raise
        except httpx.RequestError as e:
            error_msg = str(e)
            logger.error(f"T212 request error on {method} {endpoint}: {error_msg}")
            raise
        finally:
            duration = (time.monotonic() - start) * 1000
            self._log_api_call(
                method=method,
                endpoint=endpoint,
                status_code=status_code,
                request_body=json.dumps(json_body) if json_body else None,
                response_body=response_text,
                duration_ms=duration,
                error=error_msg,
            )

    # --- Account endpoints ---

    def get_cash(self) -> dict[str, Any]:
        """GET /equity/account/cash — account cash balance."""
        return self._request("GET", "/equity/account/cash")  # type: ignore[return-value]

    def get_account_summary(self) -> dict[str, Any]:
        """GET /equity/account/summary — full account value including reserved.

        Returns totalValue (cash + investments + reserved) for accurate drawdown.
        Prefer this over piecing together cash + portfolio for drawdown logic.
        """
        return self._request("GET", "/equity/account/summary")  # type: ignore[return-value]

    def get_account_info(self) -> dict[str, Any]:
        """GET /equity/account/info — account metadata."""
        return self._request("GET", "/equity/account/info")  # type: ignore[return-value]

    # --- Instrument metadata ---

    def get_instruments(self) -> list[dict[str, Any]]:
        """GET /equity/metadata/instruments — all available instruments."""
        return self._request("GET", "/equity/metadata/instruments")  # type: ignore[return-value]

    def get_exchanges(self) -> list[dict[str, Any]]:
        """GET /equity/metadata/exchanges — all exchanges."""
        return self._request("GET", "/equity/metadata/exchanges")  # type: ignore[return-value]

    # --- Portfolio ---

    def get_portfolio(self) -> list[dict[str, Any]]:
        """GET /equity/portfolio — all open positions."""
        return self._request("GET", "/equity/portfolio")  # type: ignore[return-value]

    def get_position(self, ticker: str) -> dict[str, Any]:
        """GET /equity/portfolio/{ticker} — single position.

        Returns {} when no open position exists (API returns 404). Callers can use
        pos.get('quantity', 0) to treat missing position as zero.
        """
        return self._request("GET", f"/equity/portfolio/{ticker}", ignore_404=True)  # type: ignore[return-value]

    # --- Orders ---

    def place_market_order(
        self,
        ticker: str,
        quantity: float,
    ) -> dict[str, Any]:
        """POST /equity/orders/market — place a market order.

        Positive quantity = BUY, negative quantity = SELL.
        """
        body = {
            "ticker": ticker,
            "quantity": quantity,
        }
        logger.info(f"Placing market order: {ticker} qty={quantity}")
        return self._request("POST", "/equity/orders/market", json_body=body)  # type: ignore[return-value]

    def place_limit_order(
        self,
        ticker: str,
        quantity: float,
        limit_price: float,
        time_validity: str = "DAY",
    ) -> dict[str, Any]:
        """POST /equity/orders/limit — place a limit order."""
        body = {
            "ticker": ticker,
            "quantity": quantity,
            "limitPrice": limit_price,
            "timeValidity": _t212_time_validity(time_validity),
        }
        logger.info(f"Placing limit order: {ticker} qty={quantity} @ {limit_price}")
        return self._request("POST", "/equity/orders/limit", json_body=body)  # type: ignore[return-value]

    def place_stop_order(
        self,
        ticker: str,
        quantity: float,
        stop_price: float,
        time_validity: str = "DAY",
    ) -> dict[str, Any]:
        """POST /equity/orders/stop — place a stop order."""
        body = {
            "ticker": ticker,
            "quantity": quantity,
            "stopPrice": stop_price,
            "timeValidity": _t212_time_validity(time_validity),
        }
        logger.info(f"Placing stop order: {ticker} qty={quantity} stop={stop_price}")
        return self._request("POST", "/equity/orders/stop", json_body=body)  # type: ignore[return-value]

    def get_pending_orders(self) -> list[dict[str, Any]]:
        """GET /equity/orders — all pending orders."""
        return self._request("GET", "/equity/orders")  # type: ignore[return-value]

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """DELETE /equity/orders/{orderId} — cancel a pending order."""
        logger.info(f"Cancelling order: {order_id}")
        return self._request("DELETE", f"/equity/orders/{order_id}")  # type: ignore[return-value]

    # --- History ---

    def get_order_history(self, cursor: str | None = None, limit: int = 50) -> dict[str, Any]:
        """GET /equity/history/orders — paginated order history."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/equity/history/orders", params=params)  # type: ignore[return-value]

    def get_dividend_history(self, cursor: str | None = None, limit: int = 50) -> dict[str, Any]:
        """GET /equity/history/dividends — dividend history."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/equity/history/dividends", params=params)  # type: ignore[return-value]

    def get_transaction_history(self, cursor: str | None = None, limit: int = 50) -> dict[str, Any]:
        """GET /equity/history/transactions — transaction history."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/equity/history/transactions", params=params)  # type: ignore[return-value]

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> "T212Client":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# --- Utility functions ---

def calculate_quantity(
    target_amount: float,
    price: float,
    *,
    prefer_whole_shares: bool = False,
    max_overspend_pct: float = 0.0,
    allow_fractional_fallback: bool = True,
) -> float:
    """Calculate order quantity from target amount and price.

    Default behavior returns quantity floored to 2 decimal places.
    When prefer_whole_shares is enabled, attempt an integer share count first.
    """
    if price <= 0:
        return 0.0
    if prefer_whole_shares:
        floor_shares = math.floor(target_amount / price)
        ceil_shares = math.ceil(target_amount / price)
        overspend_limit = target_amount * (1 + max(max_overspend_pct, 0.0) / 100)
        if ceil_shares > 0 and (ceil_shares * price) <= overspend_limit:
            return float(ceil_shares)
        if floor_shares > 0:
            return float(floor_shares)
        if not allow_fractional_fallback:
            return 0.0
    raw = target_amount / price
    return math.floor(raw * 100) / 100


if __name__ == "__main__":
    """Quick test: fetch account balance."""
    client = T212Client()
    try:
        cash = client.get_cash()
        print(f"Account cash: {cash}")
        info = client.get_account_info()
        print(f"Account info: {info}")
    except Exception as e:
        print(f"Error (expected if no API key configured): {e}")
    finally:
        client.close()
