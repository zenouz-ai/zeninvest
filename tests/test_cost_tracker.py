"""Tests for the cost tracker module."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.data.models import Base, CostLog
from src.utils.config import get_settings
from src.utils.cost_tracker import (
    calculate_cost,
    calculate_embedding_cost,
    log_cost,
    log_embedding_cost,
    get_daily_spend,
    get_category_daily_spend,
    get_monthly_spend,
    get_budget_status,
    check_budget,
    check_chat_budget,
    check_embedding_budget,
    get_degradation_level,
    get_cost_summary,
    Provider,
    DegradationLevel,
    USD_TO_GBP,
)


def _cost_row(provider="anthropic", cost_gbp=0.0, purpose=None):
    return CostLog(
        timestamp=datetime.now(timezone.utc),
        provider=provider,
        model="test",
        input_tokens=0,
        output_tokens=0,
        cost_gbp=cost_gbp,
        purpose=purpose,
    )


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def mock_get_session(db_session):
    """Patch get_session to use the test database."""
    with patch("src.utils.cost_tracker.get_session", return_value=db_session):
        yield


class TestCalculateCost:
    def test_anthropic_cost(self):
        # 1M input tokens = $3, 1M output tokens = $15
        cost = calculate_cost("anthropic", 1_000_000, 1_000_000)
        expected = (3.0 + 15.0) * USD_TO_GBP
        assert abs(cost - expected) < 0.01

    def test_openai_cost(self):
        cost = calculate_cost("openai", 1_000_000, 1_000_000)
        expected = (2.50 + 10.0) * USD_TO_GBP
        assert abs(cost - expected) < 0.01

    def test_google_cost(self):
        cost = calculate_cost("google", 1_000_000, 1_000_000)
        expected = (0.10 + 0.40) * USD_TO_GBP
        assert abs(cost - expected) < 0.01

    def test_zero_tokens(self):
        cost = calculate_cost("anthropic", 0, 0)
        assert cost == 0.0

    def test_unknown_provider(self):
        cost = calculate_cost("unknown", 1000, 1000)
        assert cost == 0.0

    def test_small_token_count(self):
        # 1000 tokens of anthropic input = $0.003
        cost = calculate_cost("anthropic", 1000, 0)
        expected = (1000 / 1_000_000) * 3.0 * USD_TO_GBP
        assert abs(cost - expected) < 0.001


class TestLogCost:
    def test_log_creates_entry(self, db_session):
        result = log_cost("anthropic", "claude-sonnet-4-5-20250929", 500, 200, "cycle-1", "strategy")
        assert result.provider == "anthropic"
        assert result.input_tokens == 500
        assert result.output_tokens == 200
        assert result.cost_gbp > 0

        entries = db_session.query(CostLog).all()
        assert len(entries) == 1
        assert entries[0].provider == "anthropic"
        assert entries[0].model == "claude-sonnet-4-5-20250929"


class TestDailySpend:
    def test_empty_database(self):
        assert get_daily_spend() == 0.0

    def test_with_entries(self, db_session):
        db_session.add(CostLog(
            timestamp=datetime.now(timezone.utc),
            provider="anthropic",
            model="test",
            input_tokens=1000,
            output_tokens=500,
            cost_gbp=0.05,
        ))
        db_session.commit()
        assert get_daily_spend() == 0.05
        assert get_daily_spend("anthropic") == 0.05
        assert get_daily_spend("openai") == 0.0


class TestBudgetStatus:
    def test_within_budget(self):
        status = get_budget_status("anthropic")
        assert not status.is_over_daily
        assert not status.is_over_monthly

    def test_over_daily(self, db_session):
        settings = get_settings()
        # Add entries exceeding the current configured daily limit.
        db_session.add(CostLog(
            timestamp=datetime.now(timezone.utc),
            provider="anthropic",
            model="test",
            input_tokens=0,
            output_tokens=0,
            cost_gbp=settings.anthropic_daily_gbp + 0.01,
        ))
        db_session.commit()
        status = get_budget_status("anthropic")
        assert status.is_over_daily


class TestDegradation:
    def test_full_when_no_spend(self):
        level = get_degradation_level()
        assert level == DegradationLevel.FULL

    def test_no_gemini_when_google_over(self, db_session):
        settings = get_settings()
        db_session.add(CostLog(
            timestamp=datetime.now(timezone.utc),
            provider="google",
            model="test",
            input_tokens=0,
            output_tokens=0,
            cost_gbp=settings.google_daily_gbp + 0.01,
        ))
        db_session.commit()
        level = get_degradation_level()
        assert level == DegradationLevel.NO_GEMINI

    def test_no_strategy_when_anthropic_over(self, db_session):
        settings = get_settings()
        db_session.add(CostLog(
            timestamp=datetime.now(timezone.utc),
            provider="anthropic",
            model="test",
            input_tokens=0,
            output_tokens=0,
            cost_gbp=settings.anthropic_daily_gbp + 0.01,
        ))
        db_session.commit()
        level = get_degradation_level()
        assert level == DegradationLevel.NO_STRATEGY

    def test_no_gpt4o_when_openai_over(self, db_session):
        settings = get_settings()
        db_session.add(CostLog(
            timestamp=datetime.now(timezone.utc),
            provider="openai",
            model="test",
            input_tokens=0,
            output_tokens=0,
            cost_gbp=settings.openai_daily_gbp + 0.01,
        ))
        db_session.commit()
        level = get_degradation_level()
        assert level == DegradationLevel.NO_GPT4O


class TestCostSummary:
    def test_empty_summary(self):
        summary = get_cost_summary()
        assert summary["total"] == 0.0

    def test_with_entries(self, db_session):
        db_session.add(CostLog(
            timestamp=datetime.now(timezone.utc),
            provider="anthropic",
            model="test",
            input_tokens=1000,
            output_tokens=500,
            cost_gbp=0.05,
        ))
        db_session.add(CostLog(
            timestamp=datetime.now(timezone.utc),
            provider="openai",
            model="test",
            input_tokens=2000,
            output_tokens=1000,
            cost_gbp=0.10,
        ))
        db_session.commit()
        summary = get_cost_summary()
        assert summary["anthropic"] == 0.05
        assert summary["openai"] == 0.10
        assert abs(summary["total"] - 0.15) < 0.001

    def test_category_breakdown(self, db_session):
        db_session.add(_cost_row("openai", 0.20, "conversation_composer"))
        db_session.add(_cost_row("openai", 0.05, "embedding"))
        db_session.add(_cost_row("anthropic", 0.10, "strategy"))
        db_session.commit()
        summary = get_cost_summary()
        assert summary["chat"] == 0.20
        assert summary["embedding"] == 0.05


class TestEmbeddingCost:
    def test_known_model(self):
        cost = calculate_embedding_cost("text-embedding-3-small", 1_000_000)
        expected = 0.02 * USD_TO_GBP
        assert abs(cost - expected) < 1e-6

    def test_unknown_model(self):
        assert calculate_embedding_cost("nope", 1_000_000) == 0.0

    def test_log_embedding_cost_writes_row(self, db_session):
        result = log_embedding_cost(1_000_000)
        assert result.provider == "openai"
        rows = db_session.query(CostLog).all()
        assert len(rows) == 1
        assert rows[0].purpose == "embedding"
        assert rows[0].cost_gbp > 0


class TestCategoryDailySpend:
    def test_chat_and_embedding_isolated(self, db_session):
        db_session.add(_cost_row("openai", 0.30, "conversation_composer"))
        db_session.add(_cost_row("anthropic", 0.30, "conversation_specialist_bull"))
        db_session.add(_cost_row("openai", 0.10, "embedding"))
        db_session.add(_cost_row("anthropic", 0.50, "strategy"))
        db_session.commit()
        assert abs(get_category_daily_spend("chat") - 0.60) < 1e-6
        assert abs(get_category_daily_spend("embedding") - 0.10) < 1e-6
        assert get_category_daily_spend("unknown") == 0.0


class TestCategoryBudgets:
    def test_chat_budget_blocks_at_cap(self, db_session):
        cap = get_settings().conversation_chat_llm_daily_budget_gbp
        assert check_chat_budget() is True
        db_session.add(_cost_row("openai", cap + 0.01, "conversation_composer"))
        db_session.commit()
        assert check_chat_budget() is False

    def test_embedding_budget_blocks_at_cap(self, db_session):
        cap = get_settings().learning_embedding_daily_budget_gbp
        assert check_embedding_budget() is True
        db_session.add(_cost_row("openai", cap + 0.01, "embedding"))
        db_session.commit()
        assert check_embedding_budget() is False

    def test_monthly_cap_overrides_category(self, db_session):
        monthly = get_settings().total_monthly_gbp
        db_session.add(_cost_row("anthropic", monthly + 0.01, "strategy"))
        db_session.commit()
        assert check_chat_budget() is False
        assert check_embedding_budget() is False


class TestBudgetSeparation:
    def test_chat_does_not_consume_provider_budget(self, db_session):
        # A large chat spend must not inflate the openai trading daily budget.
        db_session.add(_cost_row("openai", 5.0, "conversation_specialist_bear"))
        db_session.add(_cost_row("openai", 5.0, "embedding"))
        db_session.commit()
        status = get_budget_status("openai")
        assert status.daily_spent_gbp == 0.0
        assert not status.is_over_daily
        # But total daily spend (no provider, no exclusion) still sees it.
        assert get_daily_spend() == 10.0
