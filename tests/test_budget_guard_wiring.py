"""Tests that budget_guard is wired into the live LLM consumers (P4-1 activation).

Verifies the flag-off path is behavior-preserving (gates on budget, logs cost) and
the flag-on path reserves+settles. Uses the real cost_tracker against the shared
in-memory engine so the CostLog rows are observable.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.data.database import SessionLocal, engine
from src.data.models import Base, CostLog
from src.utils import cost_tracker as ct


@pytest.fixture(autouse=True)
def _setup_db(monkeypatch):
    # Placeholder keys so client construction (before the guard) doesn't raise;
    # the SDK clients themselves are mocked in each test.
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "test-google-key")
    Base.metadata.create_all(engine)
    s = SessionLocal()
    s.query(CostLog).delete()
    s.commit()
    s.close()
    yield
    s = SessionLocal()
    s.query(CostLog).delete()
    s.commit()
    s.close()


def _atomic_on_settings():
    return SimpleNamespace(
        atomic_budget_enabled=True,
        anthropic_daily_gbp=2.0,
        openai_daily_gbp=1.0,
        google_daily_gbp=1.0,
        total_monthly_gbp=60.0,
        alert_threshold_pct=80.0,
    )


def _cost_rows(purpose: str | None = None):
    s = SessionLocal()
    try:
        q = s.query(CostLog)
        if purpose is not None:
            q = q.filter(CostLog.purpose == purpose)
        return q.all()
    finally:
        s.close()


# --- OpenAI skeptic -----------------------------------------------------------

def _openai_response():
    resp = MagicMock()
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 1200
    resp.usage.completion_tokens = 300
    msg = MagicMock()
    msg.content = '{"verdict": "APPROVE", "reasoning": "ok"}'
    msg.tool_calls = None
    resp.choices = [MagicMock(message=msg)]
    return resp


def test_openai_single_turn_logs_cost_flag_off():
    from src.agents.moderation import openai_mod

    with patch("src.agents.moderation.openai_mod.openai.OpenAI") as mock_openai:
        mock_openai.return_value.chat.completions.create.return_value = _openai_response()
        openai_mod.review_trade({"ticker": "AAPL_US_EQ"}, "Cash 5000", {}, cycle_id="c1")

    rows = _cost_rows("moderation_gpt4o")
    assert len(rows) == 1
    assert rows[0].input_tokens == 1200
    assert rows[0].reservation_state is None  # logged, not a reservation


def test_openai_denied_when_budget_exceeded_flag_off():
    from src.agents.moderation import openai_mod

    with patch("src.utils.cost_tracker.check_budget", return_value=False), patch(
        "src.agents.moderation.openai_mod.openai.OpenAI"
    ) as mock_openai:
        result = openai_mod.review_trade({"ticker": "AAPL_US_EQ"}, "Cash 5000", {}, cycle_id="c1")
        mock_openai.return_value.chat.completions.create.assert_not_called()

    assert result["available"] is False
    assert result["verdict"] == "SKIP"
    assert _cost_rows() == []


def test_openai_single_turn_settles_reservation_flag_on():
    from src.agents.moderation import openai_mod

    with patch("src.utils.cost_tracker.get_settings", _atomic_on_settings), patch(
        "src.agents.moderation.openai_mod.openai.OpenAI"
    ) as mock_openai:
        mock_openai.return_value.chat.completions.create.return_value = _openai_response()
        openai_mod.review_trade({"ticker": "AAPL_US_EQ"}, "Cash 5000", {}, cycle_id="c1")

    rows = _cost_rows("moderation_gpt4o")
    assert len(rows) == 1  # one row: reserved then settled in place
    assert rows[0].reservation_state == ct.RESERVATION_SETTLED
    assert rows[0].input_tokens == 1200


# --- Gemini risk assessor -----------------------------------------------------

def _gemini_response():
    resp = MagicMock()
    resp.usage_metadata = MagicMock()
    resp.usage_metadata.prompt_token_count = 900
    resp.usage_metadata.candidates_token_count = 250
    resp.text = '{"growth_score": 7, "risk_score": 4, "confidence_score": 6, "reasoning": "ok"}'
    return resp


def test_gemini_single_turn_logs_cost_flag_off():
    from src.agents.moderation import gemini_mod

    with patch("src.agents.moderation.gemini_mod.genai.Client") as mock_client:
        mock_client.return_value.models.generate_content.return_value = _gemini_response()
        gemini_mod.review_trade({"ticker": "AAPL_US_EQ"}, "Cash 5000", {}, cycle_id="c1")

    rows = _cost_rows("moderation_gemini")
    assert len(rows) == 1
    assert rows[0].input_tokens == 900
    assert rows[0].reservation_state is None


def test_gemini_denied_when_budget_exceeded_flag_off():
    from src.agents.moderation import gemini_mod

    with patch("src.utils.cost_tracker.check_budget", return_value=False), patch(
        "src.agents.moderation.gemini_mod.genai.Client"
    ) as mock_client:
        result = gemini_mod.review_trade({"ticker": "AAPL_US_EQ"}, "Cash 5000", {}, cycle_id="c1")
        mock_client.return_value.models.generate_content.assert_not_called()

    assert result["available"] is False
    assert _cost_rows() == []


# --- Strategy synthesis -------------------------------------------------------

def _strategy_response():
    resp = MagicMock()
    resp.content = [MagicMock()]
    resp.content[0].text = '{"market_assessment": "ok", "decisions": [], "portfolio_commentary": "x"}'
    resp.stop_reason = "end_turn"
    resp.usage = MagicMock()
    resp.usage.input_tokens = 2000
    resp.usage.output_tokens = 500
    return resp


def _make_engine():
    from src.agents.strategy.engine import StrategyEngine

    eng = StrategyEngine()
    eng.settings._config.setdefault("research", {})["enabled"] = False
    eng._client = MagicMock()
    eng._client.messages.create.return_value = _strategy_response()
    return eng


def _synth(eng):
    return eng.synthesize_with_claude(
        sub_strategy_results={"momentum": [], "mean_reversion": [], "factor": [], "top_factor": []},
        portfolio_state="Cash 5000",
        market_regime="BULL",
        analyst_data="",
        news_sentiment="",
        macro_context="",
        company_profiles="",
        entry_quality_guards="",
        system_state="ACTIVE",
        vix=18.0,
        cash_pct=50.0,
        num_positions=3,
        cycle_id="c1",
    )


def test_strategy_single_turn_logs_cost_flag_off():
    eng = _make_engine()
    _synth(eng)
    rows = _cost_rows("strategy")
    assert len(rows) == 1
    assert rows[0].input_tokens == 2000
    assert rows[0].reservation_state is None


def test_strategy_single_turn_settles_reservation_flag_on():
    eng = _make_engine()
    with patch("src.utils.cost_tracker.get_settings", _atomic_on_settings):
        _synth(eng)
    rows = _cost_rows("strategy")
    assert len(rows) == 1
    assert rows[0].reservation_state == ct.RESERVATION_SETTLED
