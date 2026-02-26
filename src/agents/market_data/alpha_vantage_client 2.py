"""Alpha Vantage API client for market news with AI sentiment."""

import time
from datetime import datetime
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.data.database import get_session
from src.data.models import ApiLog
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("alpha_vantage")

# Rate: 25 requests/day for free tier — use strategically
_daily_request_count = 0
_MAX_DAILY_REQUESTS = 25


class AlphaVantageClient:
    """Client for Alpha Vantage API — market news sentiment."""

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.alpha_vantage_base_url
        self.api_key = settings.alpha_vantage_api_key
        self._client = httpx.Client(timeout=20.0)

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
                timestamp=datetime.utcnow(),
                service="alpha_vantage",
                method="GET",
                endpoint=endpoint,
                status_code=status_code,
                response_body=response_body[:3000] if response_body else None,
                duration_ms=duration_ms,
                error=error,
            ))
            session.commit()
        except Exception as e:
            logger.error(f"Failed to log AV API call: {e}")
            session.rollback()
        finally:
            session.close()

    def _check_daily_limit(self) -> bool:
        """Check if we've exceeded the daily request limit."""
        global _daily_request_count
        if _daily_request_count >= _MAX_DAILY_REQUESTS:
            logger.warning(f"Alpha Vantage daily limit reached ({_daily_request_count}/{_MAX_DAILY_REQUESTS})")
            return False
        return True

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
    def _request(self, params: dict[str, Any]) -> Any:
        """Make an API request to Alpha Vantage."""
        global _daily_request_count

        if not self._check_daily_limit():
            return {"error": "Daily limit reached"}

        params["apikey"] = self.api_key
        start = time.monotonic()
        error_msg = None
        status_code = None
        response_text = None

        try:
            response = self._client.get(self.base_url, params=params)
            status_code = response.status_code
            response_text = response.text
            response.raise_for_status()
            _daily_request_count += 1
            data = response.json()

            # Alpha Vantage returns errors in JSON
            if "Error Message" in data or "Note" in data:
                error_msg = data.get("Error Message") or data.get("Note", "Rate limit")
                logger.warning(f"Alpha Vantage API note: {error_msg}")

            return data
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Alpha Vantage API error: {error_msg}")
            raise
        finally:
            duration = (time.monotonic() - start) * 1000
            endpoint = params.get("function", "unknown")
            self._log_api_call(endpoint, status_code, response_text, duration, error_msg)

    def get_market_news_sentiment(
        self,
        topics: str | None = None,
        tickers: str | None = None,
        sort: str = "RELEVANCE",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Get market news with AI-generated sentiment scores.

        Args:
            topics: Comma-separated topics (technology, earnings, ipo, mergers,
                    economy_fiscal, economy_monetary, etc.)
            tickers: Comma-separated ticker symbols (e.g., "AAPL,MSFT")
            sort: Sort order (LATEST, EARLIEST, RELEVANCE)
            limit: Number of results (max 200)
        """
        params: dict[str, Any] = {
            "function": "NEWS_SENTIMENT",
            "sort": sort,
            "limit": limit,
        }
        if topics:
            params["topics"] = topics
        if tickers:
            params["tickers"] = tickers

        try:
            data = self._request(params)
            if "error" in data:
                return data

            feed = data.get("feed", [])
            processed_articles = []
            for article in feed[:limit]:
                ticker_sentiments = []
                for ts in article.get("ticker_sentiment", []):
                    ticker_sentiments.append({
                        "ticker": ts.get("ticker"),
                        "relevance_score": float(ts.get("relevance_score", 0)),
                        "sentiment_score": float(ts.get("ticker_sentiment_score", 0)),
                        "sentiment_label": ts.get("ticker_sentiment_label", "Neutral"),
                    })

                processed_articles.append({
                    "title": article.get("title"),
                    "source": article.get("source"),
                    "time_published": article.get("time_published"),
                    "overall_sentiment_score": float(article.get("overall_sentiment_score", 0)),
                    "overall_sentiment_label": article.get("overall_sentiment_label", "Neutral"),
                    "ticker_sentiments": ticker_sentiments,
                    "topics": [t.get("topic") for t in article.get("topics", [])],
                })

            # Calculate aggregate sentiment
            if processed_articles:
                avg_sentiment = sum(a["overall_sentiment_score"] for a in processed_articles) / len(processed_articles)
                bullish_count = sum(1 for a in processed_articles if a["overall_sentiment_score"] > 0.15)
                bearish_count = sum(1 for a in processed_articles if a["overall_sentiment_score"] < -0.15)
            else:
                avg_sentiment = 0.0
                bullish_count = 0
                bearish_count = 0

            return {
                "total_articles": len(processed_articles),
                "average_sentiment": round(avg_sentiment, 4),
                "bullish_articles": bullish_count,
                "bearish_articles": bearish_count,
                "neutral_articles": len(processed_articles) - bullish_count - bearish_count,
                "articles": processed_articles,
            }

        except Exception as e:
            logger.error(f"Failed to get market news sentiment: {e}")
            return {"error": str(e)}

    def get_ticker_news_summary(
        self,
        tickers: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Get news sentiment for specific tickers, formatted for LLM consumption.

        Args:
            tickers: Comma-separated ticker symbols (e.g., "AAPL,MSFT,GOOGL").
                     Multiple tickers in a single call to conserve the 25 req/day limit.
            limit: Number of articles per request.

        Returns:
            Dict with aggregate stats and top article summaries for LLMs.
        """
        data = self.get_market_news_sentiment(tickers=tickers, sort="RELEVANCE", limit=limit)
        if "error" in data:
            return data

        return {
            "tickers_queried": tickers,
            "total_articles": data.get("total_articles", 0),
            "average_sentiment": data.get("average_sentiment", 0),
            "bullish_articles": data.get("bullish_articles", 0),
            "bearish_articles": data.get("bearish_articles", 0),
            "neutral_articles": data.get("neutral_articles", 0),
            "top_articles_summary": self._summarize_articles(data.get("articles", []), max_articles=10),
        }

    @staticmethod
    def _summarize_articles(articles: list[dict[str, Any]], max_articles: int = 10) -> str:
        """Create a compact text summary of articles for LLM prompts.

        Distills each article into a single line: [SENTIMENT score] title (source).
        """
        if not articles:
            return "No recent articles found."

        lines = []
        for art in articles[:max_articles]:
            score = art.get("overall_sentiment_score", 0)
            label = art.get("overall_sentiment_label", "Neutral")
            title = art.get("title", "Untitled")[:100]
            source = art.get("source", "Unknown")
            lines.append(f"[{label} {score:+.3f}] {title} ({source})")

        return "\n".join(lines)

    def get_broad_market_sentiment(self) -> dict[str, Any]:
        """Get broad market sentiment across key topics.

        This uses one API call strategically for market-wide analysis.
        """
        return self.get_market_news_sentiment(
            topics="economy_fiscal,economy_monetary,earnings,technology",
            sort="LATEST",
            limit=50,
        )

    def close(self) -> None:
        self._client.close()
