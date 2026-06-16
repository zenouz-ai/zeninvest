"""Comprehensive tests for the agentic research module (US-4.4).

Tests: ResearchCache, ResearchBudget, ProviderRouter, ResearchExecutor,
       sec_search, tool definitions, macro_search, shared budget enforcement.
"""

import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agents.research.budget import ResearchBudget
from src.agents.research.cache import ResearchCache, _cache_key
from src.agents.research.executor import ResearchExecutor
from src.agents.research.providers.router import ProviderRouter
from src.agents.research.tools import (
    get_research_tool_definitions,
    get_research_tools_openai,
)
from src.agents.research.types import SECResult, SearchResult
from src.data.models import Base, ResearchCache as ResearchCacheRow, ResearchLog


@pytest.fixture
def db_session():
    """In-memory SQLite for research log tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def clear_cache(db_session):
    """Back the durable research cache with the in-memory test DB and clear it.

    The cache opens/closes its own sessions, so use ``side_effect`` to hand it a
    fresh session bound to the same engine on each call (closing those must not
    disturb the test's ``db_session``).
    """
    test_session_factory = sessionmaker(bind=db_session.get_bind())
    with patch("src.agents.research.cache.get_session", side_effect=test_session_factory):
        db_session.query(ResearchCacheRow).delete()
        db_session.commit()
        yield
        try:
            db_session.query(ResearchCacheRow).delete()
            db_session.commit()
        except Exception:
            db_session.rollback()


# ──────────────────────────────────────────────────────────────────
# ResearchCache
# ──────────────────────────────────────────────────────────────────

class TestResearchCache:

    def test_set_and_get(self):
        cache = ResearchCache(ttl_hours=1)
        cache.set("AAPL", "web_search", "apple news", [{"url": "x"}])
        result = cache.get("AAPL", "web_search", "apple news")
        assert result == [{"url": "x"}]

    def test_cache_miss_returns_none(self):
        cache = ResearchCache()
        assert cache.get("AAPL", "web_search", "no such query") is None

    def test_cache_ttl_expiry(self):
        cache = ResearchCache(ttl_hours=0.0001)
        cache.set("AAPL", "web_search", "test", [{"url": "y"}])
        time.sleep(0.5)
        assert cache.get("AAPL", "web_search", "test") is None

    def test_cache_normalizes_query(self):
        cache = ResearchCache()
        cache.set("AAPL", "web_search", "  Apple  News  ", [{"url": "z"}])
        assert cache.get("AAPL", "web_search", "apple news") == [{"url": "z"}]

    def test_different_tickers_different_keys(self):
        cache = ResearchCache()
        cache.set("AAPL", "web_search", "test", [{"ticker": "AAPL"}])
        cache.set("MSFT", "web_search", "test", [{"ticker": "MSFT"}])
        assert cache.get("AAPL", "web_search", "test") == [{"ticker": "AAPL"}]
        assert cache.get("MSFT", "web_search", "test") == [{"ticker": "MSFT"}]

    def test_different_tools_different_keys(self):
        cache = ResearchCache()
        cache.set("AAPL", "web_search", "test", [{"tool": "web"}])
        cache.set("AAPL", "news_search", "test", [{"tool": "news"}])
        assert cache.get("AAPL", "web_search", "test") == [{"tool": "web"}]
        assert cache.get("AAPL", "news_search", "test") == [{"tool": "news"}]

    def test_cache_key_deterministic(self):
        k1 = _cache_key("AAPL", "web_search", "test query")
        k2 = _cache_key("AAPL", "web_search", "test query")
        assert k1 == k2

    def test_cache_survives_new_instance(self):
        # Core US-9.4 win: a different ResearchCache instance (e.g. a later cycle or
        # a process restart) reads results written by an earlier instance.
        writer = ResearchCache(ttl_hours=4)
        writer.set("AAPL", "web_search", "durable", [{"url": "persisted"}])
        reader = ResearchCache(ttl_hours=4)
        assert reader.get("AAPL", "web_search", "durable") == [{"url": "persisted"}]

    def test_cache_upsert_overwrites(self):
        cache = ResearchCache()
        cache.set("AAPL", "web_search", "q", [{"v": 1}])
        cache.set("AAPL", "web_search", "q", [{"v": 2}])
        assert cache.get("AAPL", "web_search", "q") == [{"v": 2}]


# ──────────────────────────────────────────────────────────────────
# ResearchBudget
# ──────────────────────────────────────────────────────────────────

class TestResearchBudget:

    @patch("src.agents.research.budget.get_settings")
    def test_can_afford_under_limit(self, mock_settings):
        mock_settings.return_value = SimpleNamespace(
            research_max_calls_per_member_per_cycle={"strategy": 20, "skeptic": 8, "risk": 7},
            research_max_total_calls_per_cycle=35,
        )
        budget = ResearchBudget(cycle_id="test-001")
        assert budget.can_afford("strategy") is True

    @patch("src.agents.research.budget.get_settings")
    def test_member_cap_exhausted(self, mock_settings):
        mock_settings.return_value = SimpleNamespace(
            research_max_calls_per_member_per_cycle={"strategy": 2, "skeptic": 1, "risk": 1},
            research_max_total_calls_per_cycle=35,
        )
        budget = ResearchBudget(cycle_id="test-002")
        budget.record_call("strategy")
        budget.record_call("strategy")
        assert budget.can_afford("strategy") is False
        assert budget.can_afford("skeptic") is True

    @patch("src.agents.research.budget.get_settings")
    def test_total_cap_exhausted(self, mock_settings):
        mock_settings.return_value = SimpleNamespace(
            research_max_calls_per_member_per_cycle={"strategy": 100, "skeptic": 100, "risk": 100},
            research_max_total_calls_per_cycle=3,
        )
        budget = ResearchBudget(cycle_id="test-003")
        budget.record_call("strategy")
        budget.record_call("strategy")
        budget.record_call("skeptic")
        assert budget.can_afford("strategy") is False
        assert budget.can_afford("skeptic") is False
        assert budget.can_afford("risk") is False

    @patch("src.agents.research.budget.get_settings")
    def test_unknown_member_denied(self, mock_settings):
        mock_settings.return_value = SimpleNamespace(
            research_max_calls_per_member_per_cycle={"strategy": 20},
            research_max_total_calls_per_cycle=35,
        )
        budget = ResearchBudget(cycle_id="test-004")
        assert budget.can_afford("unknown_member") is False

    @patch("src.agents.research.budget.get_settings")
    def test_record_call_increments(self, mock_settings):
        mock_settings.return_value = SimpleNamespace(
            research_max_calls_per_member_per_cycle={"strategy": 20, "skeptic": 8},
            research_max_total_calls_per_cycle=35,
        )
        budget = ResearchBudget(cycle_id="test-005")
        budget.record_call("strategy")
        budget.record_call("skeptic")
        assert budget._total_calls == 2
        assert budget._member_calls["strategy"] == 1
        assert budget._member_calls["skeptic"] == 1


# ──────────────────────────────────────────────────────────────────
# ProviderRouter
# ──────────────────────────────────────────────────────────────────

class TestProviderRouter:

    @patch("src.agents.research.providers.router.TavilySearchProvider")
    @patch("src.agents.research.providers.router.BraveSearchProvider")
    def test_primary_succeeds(self, MockBrave, MockTavily):
        brave_instance = MockBrave.return_value
        tavily_instance = MockTavily.return_value
        brave_instance.search.return_value = [SearchResult("http://x.com", "Title", "Snippet")]
        router = ProviderRouter()
        router._primary = brave_instance
        router._fallback = tavily_instance

        results, provider = router.search("test query")
        assert provider == "brave"
        assert len(results) == 1
        brave_instance.search.assert_called_once()
        tavily_instance.search.assert_not_called()

    @patch("src.agents.research.providers.router.TavilySearchProvider")
    @patch("src.agents.research.providers.router.BraveSearchProvider")
    def test_fallback_on_primary_empty(self, MockBrave, MockTavily):
        brave_instance = MockBrave.return_value
        tavily_instance = MockTavily.return_value
        brave_instance.search.return_value = []
        tavily_instance.search.return_value = [SearchResult("http://y.com", "T2", "S2")]
        router = ProviderRouter()
        router._primary = brave_instance
        router._fallback = tavily_instance

        results, provider = router.search("test query")
        assert provider == "tavily"
        assert len(results) == 1

    @patch("src.agents.research.providers.router.TavilySearchProvider")
    @patch("src.agents.research.providers.router.BraveSearchProvider")
    def test_both_fail_returns_empty(self, MockBrave, MockTavily):
        brave_instance = MockBrave.return_value
        tavily_instance = MockTavily.return_value
        brave_instance.search.return_value = []
        tavily_instance.search.return_value = []
        router = ProviderRouter()
        router._primary = brave_instance
        router._fallback = tavily_instance

        results, provider = router.search("test query")
        assert provider == "brave"
        assert results == []


# ──────────────────────────────────────────────────────────────────
# Tool Definitions
# ──────────────────────────────────────────────────────────────────

class TestToolDefinitions:

    def test_tool_definitions_count(self):
        tools = get_research_tool_definitions()
        assert len(tools) == 5
        names = {t["name"] for t in tools}
        assert names == {"web_search", "news_search", "sector_search", "sec_search", "macro_search"}

    def test_tool_definitions_have_schema(self):
        for tool in get_research_tool_definitions():
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            schema = tool["input_schema"]
            assert schema["type"] == "object"
            assert "properties" in schema
            assert "required" in schema

    def test_openai_format_conversion(self):
        openai_tools = get_research_tools_openai()
        assert len(openai_tools) == 5
        for t in openai_tools:
            assert t["type"] == "function"
            assert "function" in t
            fn = t["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn

    def test_macro_search_tool_definition(self):
        tools = get_research_tool_definitions()
        macro = next(t for t in tools if t["name"] == "macro_search")
        assert "query" in macro["input_schema"]["properties"]
        assert "query" in macro["input_schema"]["required"]


# ──────────────────────────────────────────────────────────────────
# SEC Search (mocked HTTP)
# ──────────────────────────────────────────────────────────────────

class TestSECSearch:

    @patch("src.agents.research.sec_search._get_submissions")
    @patch("src.agents.research.sec_search._get_tickers_map")
    def test_sec_search_returns_results(self, mock_tickers, mock_subs):
        from src.agents.research.sec_search import sec_search

        mock_tickers.return_value = {"AAPL": {"ticker": "AAPL", "cik_str": "320193"}}
        mock_subs.return_value = {
            "recent": {
                "form": ["10-K", "10-Q", "8-K"],
                "filingDate": ["2025-11-01", "2025-08-01", "2025-07-15"],
                "primaryDocument": ["doc1.htm", "doc2.htm", "doc3.htm"],
                "accessionNumber": ["0001-23-000001", "0001-23-000002", "0001-23-000003"],
                "primaryDocDescription": ["Annual Report", "Quarterly Report", "Current Report"],
            }
        }

        results = sec_search("AAPL", doc_type="10-K", num_results=3)
        assert len(results) == 1
        assert results[0].filing_type == "10-K"
        assert results[0].filing_date == "2025-11-01"

    @patch("src.agents.research.sec_search._get_tickers_map")
    def test_sec_search_unknown_ticker(self, mock_tickers):
        from src.agents.research.sec_search import sec_search

        mock_tickers.return_value = {}
        results = sec_search("UNKNOWN_TICKER")
        assert results == []

    @patch("src.agents.research.sec_search._get_submissions")
    @patch("src.agents.research.sec_search._get_tickers_map")
    def test_sec_search_all_types(self, mock_tickers, mock_subs):
        from src.agents.research.sec_search import sec_search

        mock_tickers.return_value = {"AAPL": {"ticker": "AAPL", "cik_str": "320193"}}
        mock_subs.return_value = {
            "recent": {
                "form": ["10-K", "10-Q", "8-K"],
                "filingDate": ["2025-11-01", "2025-08-01", "2025-07-15"],
                "primaryDocument": ["d1.htm", "d2.htm", "d3.htm"],
                "accessionNumber": ["0001-23-000001", "0001-23-000002", "0001-23-000003"],
                "primaryDocDescription": ["AR", "QR", "CR"],
            }
        }

        results = sec_search("AAPL", doc_type="all", num_results=10)
        assert len(results) == 3


# ──────────────────────────────────────────────────────────────────
# ResearchExecutor (integration with mocked providers)
# ──────────────────────────────────────────────────────────────────

class TestResearchExecutor:

    def _make_executor(self, db_session, budget_caps=None):
        """Create an executor with mocked providers and real cache/budget."""
        caps = budget_caps or {"strategy": 20, "skeptic": 8, "risk": 7}
        with patch("src.agents.research.budget.get_settings") as mock_s:
            mock_s.return_value = SimpleNamespace(
                research_max_calls_per_member_per_cycle=caps,
                research_max_total_calls_per_cycle=35,
            )
            budget = ResearchBudget(cycle_id="test-exec")
        cache = ResearchCache(ttl_hours=1)
        executor = ResearchExecutor(cycle_id="test-exec", cache=cache, budget=budget)
        return executor

    @patch("src.agents.research.executor.get_settings")
    @patch("src.agents.research.executor.get_session")
    def test_web_search_with_mock_router(self, mock_session, mock_settings, db_session):
        mock_settings.return_value = SimpleNamespace(research_enabled=True)
        mock_session.return_value = db_session

        executor = self._make_executor(db_session)
        mock_router = MagicMock()
        mock_router.search.return_value = (
            [SearchResult("http://a.com", "Apple News", "Good stuff")],
            "brave",
        )
        executor._router = mock_router

        results = executor.web_search("strategy", "AAPL", "apple stock analysis")
        assert len(results) == 1
        assert results[0]["title"] == "Apple News"
        mock_router.search.assert_called_once()

    @patch("src.agents.research.executor.get_settings")
    @patch("src.agents.research.executor.get_session")
    def test_web_search_cache_hit(self, mock_session, mock_settings, db_session):
        mock_settings.return_value = SimpleNamespace(research_enabled=True)
        mock_session.return_value = db_session

        executor = self._make_executor(db_session)
        mock_router = MagicMock()
        mock_router.search.return_value = (
            [SearchResult("http://a.com", "Title", "Snippet")],
            "brave",
        )
        executor._router = mock_router

        result1 = executor.web_search("strategy", "AAPL", "test query")
        result2 = executor.web_search("strategy", "AAPL", "test query")
        assert result1 == result2
        assert mock_router.search.call_count == 1

    @patch("src.agents.research.executor.get_settings")
    @patch("src.agents.research.executor.get_session")
    def test_news_search(self, mock_session, mock_settings, db_session):
        mock_settings.return_value = SimpleNamespace(research_enabled=True)
        mock_session.return_value = db_session

        executor = self._make_executor(db_session)
        mock_router = MagicMock()
        mock_router.search.return_value = (
            [SearchResult("http://news.com", "Earnings", "Beat estimates")],
            "tavily",
        )
        executor._router = mock_router

        results = executor.news_search("skeptic", "AAPL", "AAPL Q1 2026 earnings")
        assert len(results) == 1
        mock_router.search.assert_called_once_with(
            query="AAPL Q1 2026 earnings", num_results=5, topic="finance"
        )

    @patch("src.agents.research.executor.get_settings")
    @patch("src.agents.research.executor.get_session")
    def test_sector_search(self, mock_session, mock_settings, db_session):
        mock_settings.return_value = SimpleNamespace(research_enabled=True)
        mock_session.return_value = db_session

        executor = self._make_executor(db_session)
        mock_router = MagicMock()
        mock_router.search.return_value = (
            [SearchResult("http://tech.com", "Tech", "Sector growth")],
            "brave",
        )
        executor._router = mock_router

        results = executor.sector_search("strategy", "AAPL", "Technology", "outlook 2026")
        assert len(results) == 1
        mock_router.search.assert_called_once_with(
            query="Technology outlook 2026", num_results=5, topic="finance"
        )

    @patch("src.agents.research.executor.get_settings")
    @patch("src.agents.research.executor.get_session")
    def test_macro_search(self, mock_session, mock_settings, db_session):
        mock_settings.return_value = SimpleNamespace(research_enabled=True)
        mock_session.return_value = db_session

        executor = self._make_executor(db_session)
        mock_router = MagicMock()
        mock_router.search.return_value = (
            [SearchResult("http://fed.com", "Fed", "Rate decision")],
            "brave",
        )
        executor._router = mock_router

        results = executor.macro_search("risk", "Fed rate decision March 2026")
        assert len(results) == 1
        assert results[0]["title"] == "Fed"

    @patch("src.agents.research.executor.get_settings")
    @patch("src.agents.research.executor.get_session")
    def test_sec_search_tool(self, mock_session, mock_settings, db_session):
        mock_settings.return_value = SimpleNamespace(research_enabled=True)
        mock_session.return_value = db_session

        executor = self._make_executor(db_session)
        with patch("src.agents.research.executor.sec_search") as mock_sec:
            mock_sec.return_value = [
                SECResult("10-K", "Annual Report", "2025-11-01", "0001-23-000001", "http://sec.gov/x")
            ]
            results = executor.sec_search_tool("strategy", "AAPL_US_EQ")
            assert len(results) == 1
            assert results[0]["filing_type"] == "10-K"

    @patch("src.agents.research.executor.get_settings")
    @patch("src.agents.research.executor.get_session")
    def test_budget_blocks_when_exhausted(self, mock_session, mock_settings, db_session):
        mock_settings.return_value = SimpleNamespace(research_enabled=True)
        mock_session.return_value = db_session

        executor = self._make_executor(db_session, budget_caps={"strategy": 1, "skeptic": 1, "risk": 1})
        mock_router = MagicMock()
        mock_router.search.return_value = (
            [SearchResult("http://a.com", "T", "S")],
            "brave",
        )
        executor._router = mock_router

        result1 = executor.web_search("strategy", "AAPL", "query1")
        assert len(result1) == 1
        result2 = executor.web_search("strategy", "MSFT", "query2")
        assert result2 == []

    @patch("src.agents.research.executor.get_settings")
    @patch("src.agents.research.executor.get_session")
    def test_research_disabled_returns_empty(self, mock_session, mock_settings, db_session):
        mock_settings.return_value = SimpleNamespace(research_enabled=False)
        mock_session.return_value = db_session

        executor = self._make_executor(db_session)
        assert executor.web_search("strategy", "AAPL", "test") == []
        assert executor.news_search("strategy", "AAPL", "test") == []
        assert executor.macro_search("risk", "test") == []

    @patch("src.agents.research.executor.get_settings")
    @patch("src.agents.research.executor.get_session")
    def test_log_records_to_db(self, mock_session, mock_settings, db_session):
        mock_settings.return_value = SimpleNamespace(research_enabled=True)
        mock_session.return_value = db_session

        executor = self._make_executor(db_session)
        mock_router = MagicMock()
        mock_router.search.return_value = (
            [SearchResult("http://x.com", "X", "Snippet")],
            "brave",
        )
        executor._router = mock_router

        executor.web_search("strategy", "AAPL", "test log query")

        logs = db_session.query(ResearchLog).all()
        assert len(logs) == 1
        log = logs[0]
        assert log.member == "strategy"
        assert log.ticker == "AAPL"
        assert log.tool_name == "web_search"
        assert log.provider == "brave"
        assert log.cache_hit is False
        assert log.cost_usd > 0
        assert log.latency_ms >= 0

    @patch("src.agents.research.executor.get_settings")
    @patch("src.agents.research.executor.get_session")
    def test_cache_hit_logged_with_zero_cost(self, mock_session, mock_settings, db_session):
        mock_settings.return_value = SimpleNamespace(research_enabled=True)
        mock_session.return_value = db_session

        executor = self._make_executor(db_session)
        mock_router = MagicMock()
        mock_router.search.return_value = (
            [SearchResult("http://x.com", "X", "S")],
            "brave",
        )
        executor._router = mock_router

        executor.web_search("strategy", "AAPL", "cache test")
        executor.web_search("strategy", "AAPL", "cache test")

        logs = db_session.query(ResearchLog).all()
        assert len(logs) == 2
        cache_hit_log = logs[1]
        assert cache_hit_log.cache_hit is True
        assert cache_hit_log.cost_usd == 0.0


# ──────────────────────────────────────────────────────────────────
# Shared Budget (pipeline-wide enforcement)
# ──────────────────────────────────────────────────────────────────

class TestSharedBudget:
    """Verify that a single ResearchBudget instance can be shared across
    strategy and moderation to enforce the pipeline-wide 35-call cap."""

    @patch("src.agents.research.budget.get_settings")
    def test_shared_budget_across_members(self, mock_settings):
        mock_settings.return_value = SimpleNamespace(
            research_max_calls_per_member_per_cycle={"strategy": 20, "skeptic": 8, "risk": 7},
            research_max_total_calls_per_cycle=5,
        )
        budget = ResearchBudget(cycle_id="shared-test")

        budget.record_call("strategy")
        budget.record_call("strategy")
        budget.record_call("skeptic")
        budget.record_call("skeptic")
        budget.record_call("risk")
        assert budget._total_calls == 5
        assert budget.can_afford("strategy") is False
        assert budget.can_afford("skeptic") is False
        assert budget.can_afford("risk") is False

    @patch("src.agents.research.executor.get_settings")
    @patch("src.agents.research.executor.get_session")
    @patch("src.agents.research.budget.get_settings")
    def test_two_executors_share_budget_object(
        self, mock_budget_settings, mock_session, mock_exec_settings, db_session
    ):
        """Simulate the orchestrator pattern: one budget, two executors."""
        mock_budget_settings.return_value = SimpleNamespace(
            research_max_calls_per_member_per_cycle={"strategy": 20, "skeptic": 8, "risk": 7},
            research_max_total_calls_per_cycle=3,
        )
        mock_exec_settings.return_value = SimpleNamespace(research_enabled=True)
        mock_session.return_value = db_session

        shared_cache = ResearchCache()
        shared_budget = ResearchBudget(cycle_id="shared-exec")

        strategy_exec = ResearchExecutor(cycle_id="shared-exec", cache=shared_cache, budget=shared_budget)
        mod_exec = ResearchExecutor(cycle_id="shared-exec", cache=shared_cache, budget=shared_budget)

        mock_router = MagicMock()
        mock_router.search.return_value = ([SearchResult("http://x.com", "T", "S")], "brave")
        strategy_exec._router = mock_router
        mod_exec._router = mock_router

        strategy_exec.web_search("strategy", "AAPL", "query1")
        strategy_exec.web_search("strategy", "MSFT", "query2")
        mod_exec.web_search("skeptic", "GOOG", "query3")

        assert shared_budget._total_calls == 3
        assert mod_exec.web_search("skeptic", "AMZN", "query4") == []


# ──────────────────────────────────────────────────────────────────
# Search Result Types
# ──────────────────────────────────────────────────────────────────

class TestSearchResultTypes:

    def test_search_result_fields(self):
        r = SearchResult(url="http://x.com", title="Title", snippet="Snippet", domain="x.com")
        assert r.url == "http://x.com"
        assert r.domain == "x.com"

    def test_search_result_default_domain(self):
        r = SearchResult(url="http://x.com", title="T", snippet="S")
        assert r.domain is None

    def test_sec_result_fields(self):
        r = SECResult("10-K", "Annual", "2025-11-01", "0001-23-001", "http://sec.gov/x")
        assert r.filing_type == "10-K"
        assert r.filing_date == "2025-11-01"
