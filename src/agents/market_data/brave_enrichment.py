"""Extract sector and market cap from search APIs (Brave, Tavily) using Gemini (cheapest model).

Uses Brave or Tavily for raw text, then Gemini 2.5 Flash to structure the output.
Designed for batch enrichment of instruments when Finnhub/yfinance are unavailable.
"""

import json
import re
import time
from typing import Any

import httpx
from google import genai
from google.genai import types

from src.utils.config import get_settings
from src.utils.cost_tracker import Provider, calculate_cost, check_budget, log_cost
from src.utils.logger import get_logger
from src.utils.ticker_utils import t212_to_yf
from src.utils.search_api_tracker import (
    SERVICE_BRAVE_ANSWERS,
    SERVICE_BRAVE_SEARCH,
    SERVICE_TAVILY,
    check_search_api_budget,
    log_search_api_call,
)

logger = get_logger("brave_enrichment")

# Standard sector names (align with yfinance / seed universe)
SECTOR_ALIASES = {
    "technology": "Technology",
    "tech": "Technology",
    "information technology": "Technology",
    "healthcare": "Healthcare",
    "health care": "Healthcare",
    "financial services": "Financial Services",
    "financials": "Financial Services",
    "finance": "Financial Services",
    "consumer discretionary": "Consumer Cyclical",
    "consumer cyclical": "Consumer Cyclical",
    "consumer staples": "Consumer Defensive",
    "consumer defensive": "Consumer Defensive",
    "basic materials": "Basic Materials",
    "materials": "Basic Materials",
    "industrials": "Industrials",
    "industrial": "Industrials",
    "energy": "Energy",
    "utilities": "Utilities",
    "real estate": "Real Estate",
    "communication services": "Communication Services",
    "communications": "Communication Services",
}

EXTRACTION_PROMPT = """You extract sector and market_cap from company descriptions.
Reply with ONLY this JSON, nothing else: {"sector": "StandardSectorName", "market_cap": number_in_usd_or_null}
Sector must be one of: Technology, Healthcare, Financial Services, Consumer Cyclical, Consumer Defensive, Basic Materials, Industrials, Energy, Utilities, Real Estate, Communication Services.
Market cap: numeric value in US dollars, or null if unknown. Example: 3830000000000 for $3.83 trillion.
"""


def _brave_search(symbol: str, count: int = 5) -> str:
    """Fetch web search results from Brave. Returns concatenated snippets."""
    key = get_settings().get_env_optional("BRAVE_SEARCH_API_KEY")
    if not key:
        return ""
    if not check_search_api_budget(SERVICE_BRAVE_SEARCH):
        return ""
    url = "https://api.search.brave.com/res/v1/web/search"
    params = {"q": f"{symbol} stock company sector market cap industry", "count": count}
    headers = {"X-Subscription-Token": key}
    t0 = time.perf_counter()
    try:
        resp = httpx.get(url, params=params, headers=headers, timeout=15)
        duration_ms = (time.perf_counter() - t0) * 1000
        log_search_api_call(
            service=SERVICE_BRAVE_SEARCH,
            endpoint="/res/v1/web/search",
            status_code=resp.status_code,
            duration_ms=duration_ms,
            method="GET",
        )
        if resp.status_code != 200:
            return ""
        data = resp.json()
        results = data.get("web", {}).get("results", [])
        return "\n".join(
            f"- {r.get('title', '')}: {r.get('description', '')}"
            for r in results[:5]
        )
    except Exception as e:
        duration_ms = (time.perf_counter() - t0) * 1000
        log_search_api_call(
            service=SERVICE_BRAVE_SEARCH,
            endpoint="/res/v1/web/search",
            status_code=0,
            duration_ms=duration_ms,
            method="GET",
            error=str(e),
        )
        logger.debug(f"Brave Search failed for {symbol}: {e}")
        return ""


def get_news_sentiment_fallback(ticker: str) -> str:
    """Web search fallback for analyst/news when Finnhub/Alpha Vantage fail.

    Queries Brave or Tavily with stock analyst/news sentiment; returns 200-500 char
    blob suitable for strategy prompt. Uses search API budget; only call when free APIs
    timeout or fail. Returns empty string if no key, budget exceeded, or search fails.
    """
    symbol = t212_to_yf(ticker)
    query = f"{symbol} stock analyst recommendation news sentiment"
    text = ""

    # Try Brave Search first
    key = get_settings().get_env_optional("BRAVE_SEARCH_API_KEY")
    if key and check_search_api_budget(SERVICE_BRAVE_SEARCH):
        url = "https://api.search.brave.com/res/v1/web/search"
        params = {"q": query, "count": 5}
        headers = {"X-Subscription-Token": key}
        t0 = time.perf_counter()
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=15)
            duration_ms = (time.perf_counter() - t0) * 1000
            log_search_api_call(
                service=SERVICE_BRAVE_SEARCH,
                endpoint="/res/v1/web/search",
                status_code=resp.status_code,
                duration_ms=duration_ms,
                method="GET",
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("web", {}).get("results", [])
                parts = [r.get("description", "") or r.get("title", "") for r in results[:5]]
                text = " ".join(p for p in parts if p)
        except Exception as e:
            duration_ms = (time.perf_counter() - t0) * 1000
            log_search_api_call(
                service=SERVICE_BRAVE_SEARCH,
                endpoint="/res/v1/web/search",
                status_code=0,
                duration_ms=duration_ms,
                method="GET",
                error=str(e),
            )
            logger.debug(f"Brave news fallback failed for {ticker}: {e}")

    # Fallback to Tavily
    if not text and check_search_api_budget(SERVICE_TAVILY):
        key = get_settings().get_env_optional("TAVILY_API_KEY")
        if key:
            url = "https://api.tavily.com/search"
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key.strip()}"}
            body = {
                "query": query,
                "search_depth": "basic",
                "topic": "finance",
                "max_results": 5,
                "include_answer": True,
            }
            t0 = time.perf_counter()
            try:
                resp = httpx.post(url, json=body, headers=headers, timeout=30)
                duration_ms = (time.perf_counter() - t0) * 1000
                log_search_api_call(
                    service=SERVICE_TAVILY,
                    endpoint="/search",
                    status_code=resp.status_code,
                    duration_ms=duration_ms,
                    method="POST",
                )
                if resp.status_code == 200:
                    data = resp.json()
                    ans = data.get("answer")
                    results = data.get("results", [])
                    parts = [ans] if ans else []
                    parts.extend(r.get("content", "") or r.get("title", "") for r in results[:5])
                    text = " ".join(p for p in parts if p)
            except Exception as e:
                duration_ms = (time.perf_counter() - t0) * 1000
                log_search_api_call(
                    service=SERVICE_TAVILY,
                    endpoint="/search",
                    status_code=0,
                    duration_ms=duration_ms,
                    method="POST",
                    error=str(e),
                )
                logger.debug(f"Tavily news fallback failed for {ticker}: {e}")

    if text:
        text = text.strip()[:500]
    return text


def get_news_sentiment_fallback_batch(tickers: list[str]) -> str:
    """Batch web search fallback when Alpha Vantage ticker sentiment fails.

    Single query for multiple tickers; returns combined blob for news_summary.
    Use when AV get_market_news_sentiment fails entirely.
    """
    if not tickers:
        return ""
    symbols = " ".join(t212_to_yf(t) for t in tickers[:10])
    query = f"{symbols} stock analyst recommendation news sentiment"
    text = ""

    if check_search_api_budget(SERVICE_BRAVE_SEARCH):
        key = get_settings().get_env_optional("BRAVE_SEARCH_API_KEY")
        if key:
            url = "https://api.search.brave.com/res/v1/web/search"
            params = {"q": query, "count": 8}
            headers = {"X-Subscription-Token": key}
            t0 = time.perf_counter()
            try:
                resp = httpx.get(url, params=params, headers=headers, timeout=15)
                duration_ms = (time.perf_counter() - t0) * 1000
                log_search_api_call(
                    service=SERVICE_BRAVE_SEARCH,
                    endpoint="/res/v1/web/search",
                    status_code=resp.status_code,
                    duration_ms=duration_ms,
                    method="GET",
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("web", {}).get("results", [])
                    parts = [r.get("description", "") or r.get("title", "") for r in results[:8]]
                    text = " ".join(p for p in parts if p)
            except Exception as e:
                duration_ms = (time.perf_counter() - t0) * 1000
                log_search_api_call(
                    service=SERVICE_BRAVE_SEARCH,
                    endpoint="/res/v1/web/search",
                    status_code=0,
                    duration_ms=duration_ms,
                    method="GET",
                    error=str(e),
                )
                logger.debug(f"Brave batch news fallback failed: {e}")

    if not text and check_search_api_budget(SERVICE_TAVILY):
        key = get_settings().get_env_optional("TAVILY_API_KEY")
        if key:
            url = "https://api.tavily.com/search"
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key.strip()}"}
            body = {
                "query": query,
                "search_depth": "basic",
                "topic": "finance",
                "max_results": 8,
                "include_answer": True,
            }
            t0 = time.perf_counter()
            try:
                resp = httpx.post(url, json=body, headers=headers, timeout=30)
                duration_ms = (time.perf_counter() - t0) * 1000
                log_search_api_call(
                    service=SERVICE_TAVILY,
                    endpoint="/search",
                    status_code=resp.status_code,
                    duration_ms=duration_ms,
                    method="POST",
                )
                if resp.status_code == 200:
                    data = resp.json()
                    ans = data.get("answer")
                    results = data.get("results", [])
                    parts = [ans] if ans else []
                    parts.extend(r.get("content", "") or r.get("title", "") for r in results[:8])
                    text = " ".join(p for p in parts if p)
            except Exception as e:
                duration_ms = (time.perf_counter() - t0) * 1000
                log_search_api_call(
                    service=SERVICE_TAVILY,
                    endpoint="/search",
                    status_code=0,
                    duration_ms=duration_ms,
                    method="POST",
                    error=str(e),
                )
                logger.debug(f"Tavily batch news fallback failed: {e}")

    if text:
        text = text.strip()[:800]
    return text


def _tavily_search(symbol: str, max_results: int = 5) -> str:
    """Fetch search results + LLM answer from Tavily (topic=finance)."""
    key = get_settings().get_env_optional("TAVILY_API_KEY")
    if not key:
        return ""
    if not check_search_api_budget(SERVICE_TAVILY):
        return ""
    key = key.strip()
    url = "https://api.tavily.com/search"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    body = {
        "query": f"{symbol} stock company sector market cap industry",
        "search_depth": "basic",
        "topic": "finance",
        "max_results": max_results,
        "include_answer": True,
    }
    t0 = time.perf_counter()
    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=30)
        duration_ms = (time.perf_counter() - t0) * 1000
        log_search_api_call(
            service=SERVICE_TAVILY,
            endpoint="/search",
            status_code=resp.status_code,
            duration_ms=duration_ms,
            method="POST",
        )
        if resp.status_code != 200:
            if resp.status_code == 401:
                logger.debug("Tavily 401: verify TAVILY_API_KEY at app.tavily.com")
            return ""
        data = resp.json()
        parts: list[str] = []
        ans = data.get("answer")
        if ans:
            parts.append(f"[Tavily Answer]\n{ans}")
        results = data.get("results", [])
        if results:
            snippets = "\n".join(
                f"- {r.get('title', '')}: {r.get('content', '')}"
                for r in results[:5]
            )
            parts.append(f"[Tavily Search]\n{snippets}")
        return "\n\n".join(parts)
    except Exception as e:
        duration_ms = (time.perf_counter() - t0) * 1000
        log_search_api_call(
            service=SERVICE_TAVILY,
            endpoint="/search",
            status_code=0,
            duration_ms=duration_ms,
            method="POST",
            error=str(e),
        )
        logger.debug(f"Tavily Search failed for {symbol}: {e}")
        return ""


def _brave_answers(symbol: str) -> str:
    """Fetch AI-generated answer from Brave Answers. Returns answer text."""
    key = get_settings().get_env_optional("BRAVE_ANSWER_API_KEY")
    if not key:
        return ""
    if not check_search_api_budget(SERVICE_BRAVE_ANSWERS):
        return ""
    url = "https://api.search.brave.com/res/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "x-subscription-token": key,
    }
    body = {
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": f"What is {symbol}'s (or the company with ticker {symbol}) business sector/industry and current market capitalization? Answer in 2-3 sentences.",
            }
        ],
    }
    t0 = time.perf_counter()
    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=30)
        duration_ms = (time.perf_counter() - t0) * 1000
        log_search_api_call(
            service=SERVICE_BRAVE_ANSWERS,
            endpoint="/res/v1/chat/completions",
            status_code=resp.status_code,
            duration_ms=duration_ms,
            method="POST",
        )
        if resp.status_code != 200:
            return ""
        data = resp.json()
        choice = data.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        return content
    except Exception as e:
        duration_ms = (time.perf_counter() - t0) * 1000
        log_search_api_call(
            service=SERVICE_BRAVE_ANSWERS,
            endpoint="/res/v1/chat/completions",
            status_code=0,
            duration_ms=duration_ms,
            method="POST",
            error=str(e),
        )
        logger.debug(f"Brave Answers failed for {symbol}: {e}")
        return ""


def _gemini_extract(
    text: str,
    ticker: str,
    cycle_id: str | None = None,
    *,
    metrics_out: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Use Gemini (cheapest model) to extract sector and market_cap from text.

    If metrics_out is provided, populates it with input_tokens, output_tokens, cost_gbp.
    """
    settings = get_settings()
    if not check_budget(Provider.GOOGLE.value):
        logger.warning("Google budget exceeded, skipping Brave enrichment")
        if metrics_out is not None:
            metrics_out.update({"input_tokens": 0, "output_tokens": 0, "cost_gbp": 0.0})
        return {"sector": None, "market_cap": None, "error": "budget_exceeded"}

    user_prompt = f"""Ticker: {ticker}

Text:
{text}

Extract sector and market_cap. JSON only."""

    try:
        client = genai.Client(api_key=settings.google_ai_api_key)
        response = client.models.generate_content(
            model=settings.moderator_2_model,  # gemini-2.5-flash (cheapest)
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=EXTRACTION_PROMPT,
                max_output_tokens=512,
                temperature=0,
            ),
        )

        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

        log_cost(
            provider=Provider.GOOGLE.value,
            model=settings.moderator_2_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cycle_id=cycle_id or "brave_enrich",
            purpose="brave_enrichment_extract",
        )
        if metrics_out is not None:
            metrics_out["input_tokens"] = input_tokens
            metrics_out["output_tokens"] = output_tokens
            metrics_out["cost_gbp"] = calculate_cost(
                Provider.GOOGLE.value, input_tokens, output_tokens
            )

        content = (response.text or "").strip()
        for marker in ["```json", "```"]:
            if marker in content:
                parts = content.split(marker)
                if len(parts) >= 2:
                    content = parts[1].split("```")[0].strip()
                    break

        # Repair common LLM output issues
        content = re.sub(r",\s*}", "}", content)
        content = re.sub(r",\s*]", "]", content)

        result = json.loads(content)
        sector = result.get("sector")
        if sector and isinstance(sector, str):
            sector = sector.strip()
            low = sector.lower()
            sector = SECTOR_ALIASES.get(low, sector)
        market_cap = result.get("market_cap")
        if isinstance(market_cap, (int, float)):
            if market_cap < 0:
                market_cap = None
            elif market_cap < 1e8 and market_cap > 0:
                # Likely parsing error (e.g. 77.5B as 77.5) - treat as unknown
                market_cap = None
            else:
                market_cap = int(market_cap)
        else:
            market_cap = None
        return {"sector": sector or None, "market_cap": market_cap, "error": None}
    except json.JSONDecodeError as e:
        logger.debug(f"Gemini extraction JSON parse failed for {ticker}: {e}, raw: {content[:200]}")
        # Regex fallback
        sector_match = re.search(r'"sector"\s*:\s*"([^"]*)"', content)
        cap_match = re.search(r'"market_cap"\s*:\s*([\d.eE+-]+|null)', content)
        sector = sector_match.group(1).strip() if sector_match else None
        if sector:
            low = sector.lower()
            sector = SECTOR_ALIASES.get(low, sector)
        try:
            raw = cap_match.group(1) if cap_match else None
            market_cap = int(float(raw)) if raw and raw != "null" else None
            if market_cap is not None and market_cap < 1e8:
                market_cap = None  # Likely parsing error
        except (ValueError, AttributeError, TypeError):
            market_cap = None
        if metrics_out is not None:
            metrics_out.update({"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_gbp": calculate_cost(Provider.GOOGLE.value, input_tokens, output_tokens)})
        if sector or market_cap:
            return {"sector": sector, "market_cap": market_cap, "error": None}
        return {"sector": None, "market_cap": None, "error": "parse_failed"}
    except Exception as e:
        logger.warning(f"Gemini extraction failed for {ticker}: {e}")
        if metrics_out is not None:
            metrics_out.update({"input_tokens": 0, "output_tokens": 0, "cost_gbp": 0.0})
        return {"sector": None, "market_cap": None, "error": str(e)}


def extract_sector_market_cap_brave_search(
    ticker: str,
    cycle_id: str | None = None,
    metrics_out: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract using Brave Web Search only + Gemini."""
    symbol = t212_to_yf(ticker)
    text = _brave_search(symbol)
    if not text.strip():
        return {"sector": None, "market_cap": None, "error": "no_data"}
    return _gemini_extract(text[:2500], ticker, cycle_id, metrics_out=metrics_out)


def extract_sector_market_cap_brave_answers(
    ticker: str,
    cycle_id: str | None = None,
    metrics_out: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract using Brave Answers only + Gemini."""
    symbol = t212_to_yf(ticker)
    text = _brave_answers(symbol)
    if not text.strip():
        return {"sector": None, "market_cap": None, "error": "no_data"}
    return _gemini_extract(text[:2500], ticker, cycle_id, metrics_out=metrics_out)


def extract_sector_market_cap(
    ticker: str,
    *,
    use_search: bool = True,
    use_answers: bool = True,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    """Extract sector and market cap using Brave APIs + Gemini.

    Args:
        ticker: T212 ticker (AAPL_US_EQ) or yfinance symbol (AAPL).
        use_search: Whether to use Brave Web Search.
        use_answers: Whether to use Brave Answers.
        cycle_id: Optional cycle id for cost tracking.

    Returns:
        Dict with keys: sector (str|None), market_cap (float|None), error (str|None).
    """
    symbol = t212_to_yf(ticker)
    parts: list[str] = []

    if use_answers:
        ans = _brave_answers(symbol)
        if ans:
            parts.append(f"[Brave Answers]\n{ans}")

    if use_search:
        search_text = _brave_search(symbol)
        if search_text:
            parts.append(f"[Brave Search]\n{search_text}")

    combined = "\n\n".join(parts)
    if not combined.strip():
        return {"sector": None, "market_cap": None, "error": "no_brave_data"}

    # Limit input size to avoid token limits / truncation
    return _gemini_extract(combined[:2500], ticker, cycle_id)


def extract_sector_market_cap_tavily(
    ticker: str,
    cycle_id: str | None = None,
    metrics_out: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract sector and market cap using Tavily Search (finance topic) + Gemini.

    Tavily returns both search snippets and an LLM-generated answer in one call,
    often with stronger finance focus than Brave.

    Args:
        ticker: T212 ticker (AAPL_US_EQ) or yfinance symbol (AAPL).
        cycle_id: Optional cycle id for cost tracking.
        metrics_out: Optional dict to receive input_tokens, output_tokens, cost_gbp.

    Returns:
        Dict with keys: sector (str|None), market_cap (float|None), error (str|None).
    """
    symbol = t212_to_yf(ticker)
    combined = _tavily_search(symbol)
    if not combined.strip():
        return {"sector": None, "market_cap": None, "error": "no_tavily_data"}
    return _gemini_extract(combined[:2500], ticker, cycle_id, metrics_out=metrics_out)
