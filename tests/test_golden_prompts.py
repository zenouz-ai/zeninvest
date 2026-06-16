"""L0 golden tests for committee prompts and research budget invariants (US-9.9)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agents.moderation.panel import ModerationPanel
from src.agents.research.budget import ResearchBudget
from src.agents.research.executor import ResearchExecutor
from src.agents.research.types import SearchResult
from src.agents.strategy.engine import StrategyEngine
from src.agents.strategy.prompts import get_strategy_prompt_hash
from src.agents.moderation import openai_mod, gemini_mod
from src.data.models import Base, ModerationLog
from src.utils.phase_timer import PhaseTimer
from src.utils.prompt_loader import load_prompt_file

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "golden"


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def mock_db(db_session):
    with patch("src.agents.moderation.panel.get_session", return_value=db_session):
        with patch("src.utils.cost_tracker.get_session", return_value=db_session):
            yield


class TestGoldenPromptFiles:
    def test_committee_prompt_files_load(self) -> None:
        for name in ("strategy_system.md", "strategy_user.md", "skeptic.md", "risk_assessor.md"):
            text = load_prompt_file(name)
            assert len(text) > 50

    def test_prompt_hashes_are_stable(self) -> None:
        first = get_strategy_prompt_hash("claude-test-model")
        second = get_strategy_prompt_hash("claude-test-model")
        assert first == second
        assert len(first) == 64

    def test_all_three_committee_hashes_distinct(self) -> None:
        strategy_hash = get_strategy_prompt_hash("model-a")
        skeptic_hash = openai_mod.get_skeptic_prompt_hash("gpt-test")
        risk_hash = gemini_mod.get_risk_assessor_prompt_hash("gemini-test")
        assert strategy_hash != skeptic_hash
        assert strategy_hash != risk_hash
        assert skeptic_hash != risk_hash


class TestGoldenStrategySchema:
    def test_frozen_strategy_response_passes_validation(self) -> None:
        payload = json.loads((_FIXTURES / "strategy_response.json").read_text(encoding="utf-8"))
        validated = StrategyEngine._validate_decisions(payload)
        assert len(validated["decisions"]) == 1
        decision = validated["decisions"][0]
        assert decision["ticker"] == "AAPL_US_EQ"
        assert decision["action"] == "BUY"
        assert decision["conviction"] == 78
        assert decision["exit_trigger_type"] == "none"

    def test_invalid_strategy_action_is_dropped(self) -> None:
        payload = {
            "market_assessment": "test",
            "decisions": [
                {
                    "ticker": "BAD_US_EQ",
                    "action": "YOLO",
                    "target_allocation_pct": 5.0,
                    "conviction": 50,
                    "primary_strategy": "momentum",
                    "reasoning": "invalid action",
                    "growth_potential": "LOW",
                    "risk_level": "HIGH",
                    "catalysts": [],
                    "risks": [],
                    "exit_conditions": "n/a",
                    "exit_trigger_type": "none",
                }
            ],
            "portfolio_commentary": "test",
        }
        validated = StrategyEngine._validate_decisions(payload)
        assert validated["decisions"] == []


class TestGoldenModerationConsensus:
    @patch("src.agents.moderation.panel.get_degradation_level")
    @patch("src.agents.moderation.gemini_mod.review_trade")
    @patch("src.agents.moderation.openai_mod.review_trade")
    def test_panel_produces_consensus_and_prompt_hashes(
        self,
        mock_gpt,
        mock_gemini,
        mock_degrade,
        db_session,
    ) -> None:
        from src.utils.cost_tracker import DegradationLevel

        mock_degrade.return_value = DegradationLevel.FULL
        mock_gpt.return_value = {
            "available": True,
            "verdict": "AGREE",
            "confidence_score": 8,
            "reasoning": "Signals align.",
            "input_tokens": 100,
            "output_tokens": 50,
            "cost_gbp": 0.01,
        }
        mock_gemini.return_value = {
            "available": True,
            "verdict": "AGREE",
            "growth_score": 7,
            "risk_score": 4,
            "confidence_score": 7,
            "assessment": "Balanced risk/reward.",
            "high_risk_flag": False,
            "moderator": "gemini-2.0-flash",
            "input_tokens": 90,
            "output_tokens": 40,
            "cost_gbp": 0.002,
        }

        panel = ModerationPanel()
        result = panel.review_trade(
            trade_proposal={
                "ticker": "AAPL_US_EQ",
                "action": "BUY",
                "target_allocation_pct": 5.0,
                "conviction": 78,
                "reasoning": "Test proposal",
            },
            portfolio_context="cash=10%",
            market_context={"indicators": {}, "fundamentals": {}},
            conviction=78,
            cycle_id="golden-cycle",
        )

        assert result.consensus in {"APPROVED", "CAUTION", "BLOCKED"}
        logs = db_session.query(ModerationLog).filter(ModerationLog.cycle_id == "golden-cycle").all()
        assert len(logs) == 3
        hashes = {log.moderator: log.prompt_hash for log in logs}
        assert all(len(h) == 64 for h in hashes.values())
        assert logs[1].input_tokens == 100
        assert logs[1].cost_gbp == pytest.approx(0.01)


class TestGoldenResearchBudgetCaps:
    @patch("src.agents.research.budget.get_settings")
    def test_member_caps_20_8_7(self, mock_settings) -> None:
        mock_settings.return_value = SimpleNamespace(
            research_max_calls_per_member_per_cycle={"strategy": 20, "skeptic": 8, "risk": 7},
            research_max_total_calls_per_cycle=35,
        )
        budget = ResearchBudget(cycle_id="golden-budget")
        for _ in range(20):
            assert budget.can_afford("strategy") is True
            budget.record_call("strategy")
        assert budget.can_afford("strategy") is False
        assert budget.can_afford("skeptic") is True

        for _ in range(8):
            budget.record_call("skeptic")
        assert budget.can_afford("skeptic") is False

        for _ in range(7):
            budget.record_call("risk")
        assert budget.can_afford("risk") is False

    @patch("src.agents.research.executor.get_settings")
    @patch("src.agents.research.executor.get_session")
    def test_executor_respects_total_cap_35(self, mock_session, mock_settings, db_session) -> None:
        mock_settings.return_value = SimpleNamespace(research_enabled=True)
        mock_session.return_value = db_session

        with patch("src.agents.research.budget.get_settings") as mock_budget_settings:
            mock_budget_settings.return_value = SimpleNamespace(
                research_max_calls_per_member_per_cycle={"strategy": 20, "skeptic": 8, "risk": 7},
                research_max_total_calls_per_cycle=2,
            )
            budget = ResearchBudget(cycle_id="golden-total")
            from src.agents.research.cache import ResearchCache

            executor = ResearchExecutor(
                cycle_id="golden-total",
                cache=ResearchCache(ttl_hours=1),
                budget=budget,
            )
            from unittest.mock import MagicMock

            mock_router = MagicMock()
            mock_router.search.return_value = (
                [SearchResult("http://a.com", "T", "S")],
                "brave",
            )
            executor._router = mock_router

            assert len(executor.web_search("strategy", "AAPL", "q1")) == 1
            assert len(executor.web_search("skeptic", "MSFT", "q2")) == 1
            assert executor.web_search("risk", "GOOG", "q3") == []


class TestGoldenPhaseTimer:
    def test_phase_timer_serializes_elapsed_phases(self) -> None:
        timer = PhaseTimer()
        timer.add_elapsed("moderation", 1.25)
        timer.add_elapsed("risk", 0.5)
        payload = timer.to_dict()
        assert payload["moderation"]["seconds"] == pytest.approx(1.25)
        assert payload["risk"]["seconds"] == pytest.approx(0.5)
