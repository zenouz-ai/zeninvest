"""SEC EDGAR client — direct HTTP, no API key. 10-K, 10-Q, 8-K, proxy."""

import time
from typing import Any

import httpx

from src.agents.research.types import SECResult
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("research.sec")

USER_AGENT = "InvestmentAgent research@example.com"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL_TEMPLATE = "https://data.sec.gov/submissions/CIK{cik}.json"
TIMEOUT = 15

# Doc type filter: map tool doc_type to SEC form codes
DOC_TYPE_MAP = {
    "10-K": ["10-K"],
    "10-Q": ["10-Q"],
    "8-K": ["8-K"],
    "proxy": ["DEF 14A", "DEFA14A"],
    "all": ["10-K", "10-Q", "8-K", "DEF 14A", "DEFA14A"],
}


def _ticker_to_clean(ticker: str) -> str:
    """T212 ticker to plain symbol (e.g. AAPL_US_EQ -> AAPL)."""
    return ticker.replace("_US_EQ", "").replace("_UK_EQ", "").strip().upper()


def _get_tickers_map() -> dict[str, dict[str, Any]]:
    """Fetch company_tickers.json; return ticker -> row map."""
    headers = {"User-Agent": get_settings().get_env_optional("SEC_EDGAR_EMAIL") or USER_AGENT}
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(TICKERS_URL, headers=headers)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        return {str(v.get("ticker", "")).upper(): v for v in data.values() if v.get("ticker")}
    except Exception as e:
        logger.debug(f"SEC tickers fetch failed: {e}")
        return {}


def _get_submissions(cik: str | int) -> dict[str, Any]:
    """Fetch submissions for CIK."""
    cik_padded = str(cik).zfill(10)
    url = SUBMISSIONS_URL_TEMPLATE.format(cik=cik_padded)
    headers = {"User-Agent": get_settings().get_env_optional("SEC_EDGAR_EMAIL") or USER_AGENT}
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(url, headers=headers)
        if resp.status_code != 200:
            return {}
        return resp.json()
    except Exception as e:
        logger.debug(f"SEC submissions fetch failed for CIK {cik}: {e}")
        return {}


def sec_search(ticker: str, doc_type: str = "10-K", num_results: int = 3) -> list[SECResult]:
    """Search SEC filings for a company.

    Args:
        ticker: Ticker (e.g. AAPL_US_EQ or AAPL).
        doc_type: 10-K, 10-Q, 8-K, proxy, or all.
        num_results: Max filings to return.

    Returns:
        List of SECResult; empty on failure.
    """
    symbol = _ticker_to_clean(ticker)
    t0 = time.perf_counter()

    tickers_map = _get_tickers_map()
    row = tickers_map.get(symbol)
    if not row:
        logger.debug(f"SEC: ticker {symbol} not found in company_tickers")
        return []

    cik = row.get("cik_str") or row.get("cik")
    if cik is None:
        return []

    sub = _get_submissions(cik)
    if not sub:
        return []

    recent = sub.get("recent") or {}
    forms = recent.get("form") or []
    filing_dates = recent.get("filingDate") or []
    primary_docs = recent.get("primaryDocument") or []
    accession_numbers = recent.get("accessionNumber") or []
    descriptions = recent.get("primaryDocDescription") or []

    allowed = DOC_TYPE_MAP.get(doc_type.lower(), DOC_TYPE_MAP["10-K"])
    results: list[SECResult] = []
    seen: set[tuple[str, str]] = set()

    for i, form in enumerate(forms):
        if form not in allowed:
            continue
        acc_raw = accession_numbers[i] if i < len(accession_numbers) else ""
        acc = (acc_raw or "").replace("-", "")
        key = (form, acc)
        if key in seen:
            continue
        seen.add(key)
        if len(results) >= num_results:
            break
        fd = filing_dates[i] if i < len(filing_dates) else ""
        doc = primary_docs[i] if i < len(primary_docs) else ""
        desc = descriptions[i] if i < len(descriptions) else None
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}" if acc and doc else ""
        results.append(
            SECResult(
                filing_type=form,
                description=desc,
                filing_date=fd,
                accession_number=acc_raw or acc,
                url=url,
            )
        )

    _ = time.perf_counter() - t0  # Log if needed
    return results
