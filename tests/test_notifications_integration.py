from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data.models import Base
from src.orchestrator.main import Orchestrator

try:
    from dashboard.backend.app.database import Base as DashboardBase
except ImportError:
    DashboardBase = None
from src.orchestrator.state_machine import StateMachine
from src.utils.cost_tracker import DegradationLevel


class CaptureNotifications:
    def __init__(self) -> None:
        self.instruction_payloads: list[dict] = []
        self.execution_payloads: list[dict] = []
        self.summary_payloads: list[dict] = []
        self.state_payloads: list[dict] = []
        self.critical_payloads: list[dict] = []

    def emit_trade_instruction_approved(self, *, cycle_id, payload, source="orchestrator") -> None:
        self.instruction_payloads.append(payload)

    def emit_trade_execution_result(self, *, cycle_id, payload, source="orchestrator") -> None:
        self.execution_payloads.append(payload)

    def emit_cycle_run_summary(self, *, cycle_id, payload, source="orchestrator") -> None:
        self.summary_payloads.append(payload)

    def emit_state_transition(self, *, cycle_id, payload, source="state_machine") -> None:
        self.state_payloads.append(payload)

    def emit_critical_cycle_failure(self, *, cycle_id, payload, source="orchestrator") -> None:
        self.critical_payloads.append(payload)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    if DashboardBase is not None:
        DashboardBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def patch_all_get_session(db_session):
    """Patch get_session everywhere it's imported from."""
    targets = [
        "src.data.database.get_session",
        "src.orchestrator.state_machine.get_session",
        "src.orchestrator.main.get_session",
        "src.utils.cost_tracker.get_session",
        "src.agents.notifications.service.get_session",
        "src.agents.execution.order_manager.get_session",
        "src.agents.execution.stop_loss_manager.get_session",
        "src.agents.execution.t212_client.get_session",
        "src.agents.moderation.panel.get_session",
        "src.agents.risk.risk_manager.get_session",
        "src.agents.strategy.engine.get_session",
        "src.agents.market_data.data_fetcher.get_session",
        "src.agents.reporting.performance_tracker.get_session",
        "src.agents.reporting.trade_outcome_tracker.get_session",
        "src.agents.opportunity.scorer.get_session",
        "src.agents.opportunity.optimizer.get_session",
        "dashboard.backend.app.services.event_logger.get_session",
    ]
    patches = []
    for target in targets:
        try:
            p = patch(target, return_value=db_session)
            p.start()
            patches.append(p)
        except (AttributeError, ModuleNotFoundError):
            pass
    yield
    for p in patches:
        p.stop()


def test_orchestrator_paused_emits_cycle_summary(monkeypatch) -> None:
    orchestrator = Orchestrator(dry_run=True)
    notifications = CaptureNotifications()
    orchestrator.notification_service = notifications
    orchestrator.state_machine = SimpleNamespace(is_paused=True)

    monkeypatch.setattr("src.orchestrator.main.get_cost_summary", lambda days=1: {})

    result = orchestrator.run_cycle()

    assert result["status"] == "paused"
    assert len(notifications.summary_payloads) == 1


def test_orchestrator_emits_instruction_and_summary(monkeypatch) -> None:
    orchestrator = Orchestrator(dry_run=True)
    notifications = CaptureNotifications()
    orchestrator.notification_service = notifications

    class DummyStateMachine:
        is_paused = False
        current_state = "ACTIVE"

        @staticmethod
        def update_peak(current_value: float) -> None:
            return

        @staticmethod
        def get_state() -> dict:
            return {"peak_portfolio_value": 10000.0, "daily_loss_halt_until": None}

        @staticmethod
        def transition(new_state: str, notes: str | None = None) -> None:
            return

        @staticmethod
        def update_drawdown(drawdown_pct: float) -> None:
            return

        @staticmethod
        def record_cycle() -> None:
            return

    orchestrator.state_machine = DummyStateMachine()
    orchestrator.settings._config.setdefault("opportunity", {})["enabled"] = False

    decision = {
        "ticker": "AAPL_US_EQ",
        "action": "BUY",
        "conviction": 82,
        "target_allocation_pct": 8,
        "reasoning": "Strong trend and supportive sentiment",
        "stop_loss_pct": -8.0,
        "primary_strategy": "momentum",
        "news_sentiment_summary": "Bullish product cycle",
    }

    orchestrator._get_portfolio_state = lambda: {
        "cash": 10000.0,
        "total_value": 10000.0,
        "invested": 0.0,
        "positions": [],
        "num_positions": 0,
        "daily_pnl_pct": 0.0,
        "total_return_pct": 0.0,
        "alpha_pct": 0.0,
    }
    orchestrator._fetch_stocks_data = lambda current_positions, exclude_tickers=None, system_state="ACTIVE": [
        {
            "ticker": "AAPL_US_EQ",
            "name": "Apple Inc.",
            "indicators": {"current_price": 180},
            "fundamentals": {
                "industry": "Consumer Electronics",
                "market_cap": 2_800_000_000_000,
                "business_summary": "Apple builds hardware and software ecosystems.",
                "trailing_pe": 28,
                "pb_ratio": 40,
                "roe": 0.6,
                "profit_margin": 0.24,
                "debt_equity": 1.4,
                "earnings_growth": 0.12,
            },
        },
    ]

    orchestrator.data_fetcher = SimpleNamespace(
        get_macro_data=lambda: {"vix": 18, "market_regime": "BULL"},
        get_cached_news_sentiment=lambda ticker, source, data_type: None,
        cache_news_sentiment=lambda *args, **kwargs: None,
        get_analyst_data_cached=lambda ticker: {},
        alpha_vantage=SimpleNamespace(get_broad_market_sentiment=lambda: {}),
        get_market_news_sentiment=lambda **kwargs: {"articles": [], "total_articles": 0},
        close=lambda: None,
    )

    orchestrator.strategy_engine = SimpleNamespace(
        run_sub_strategies=lambda stocks_data, existing_tickers: {
            "momentum": [],
            "mean_reversion": [],
            "top_factor": [],
            "factor": [],
        },
        synthesize_with_claude=lambda **kwargs: {"decisions": [decision], "market_assessment": ""},
    )

    class DummyMod:
        consensus = "APPROVED"

        @staticmethod
        def to_dict() -> dict:
            return {
                "consensus": "APPROVED",
                "gpt4o_verdict": {"reasoning": "Looks reasonable"},
                "gemini_verdict": {
                    "assessment": "Risk manageable",
                    "growth_score": 7,
                    "risk_score": 4,
                    "confidence_score": 7,
                },
            }

    class DummyRisk:
        verdict = "APPROVE"
        adjusted_allocation_pct = 8
        triggered_rules: list[str] = []
        rules_checked: list[str] = []
        reasoning = "All checks passed"

    orchestrator.moderation_panel = SimpleNamespace(review_trade=lambda **kwargs: DummyMod())
    orchestrator.risk_manager = SimpleNamespace(
        evaluate_trade=lambda **kwargs: DummyRisk(),
        get_drawdown_state=lambda current_value, peak_value: "ACTIVE",
    )
    orchestrator._save_snapshot = lambda portfolio_data, state: None
    orchestrator._execute_trade = lambda **kwargs: {
        "ticker": kwargs["ticker"],
        "action": kwargs["action"],
        "execution": {"status": "dry_run", "quantity": 1, "value_gbp": 800},
        "stop_loss": {"status": "placed"},
    }

    monkeypatch.setattr("src.orchestrator.main.get_degradation_level", lambda: DegradationLevel.FULL)
    monkeypatch.setattr("src.orchestrator.main.get_cost_summary", lambda days=1: {})

    result = orchestrator.run_cycle()

    assert result["status"] == "completed"
    assert len(notifications.instruction_payloads) == 1
    assert notifications.instruction_payloads[0]["ticker"] == "AAPL_US_EQ"
    assert len(notifications.summary_payloads) == 1


def test_execute_trade_emits_execution_notification(monkeypatch) -> None:
    orchestrator = Orchestrator(dry_run=True)
    notifications = CaptureNotifications()
    orchestrator.notification_service = notifications

    class DummyOrderManager:
        @staticmethod
        def execute_market_order(**kwargs):
            return {"status": "dry_run", "quantity": 2, "value_gbp": 20}

        @staticmethod
        def place_stop_loss(**kwargs):
            return {"status": "placed", "stop_price": 9.2}

    class DummyMod:
        consensus = "APPROVED"

        @staticmethod
        def to_dict() -> dict:
            return {"consensus": "APPROVED"}

    class DummyRisk:
        verdict = "APPROVE"
        rules_checked = []
        triggered_rules = []
        reasoning = "ok"

    orchestrator._order_manager = DummyOrderManager()
    monkeypatch.setattr("src.orchestrator.main.generate_trade_journal", lambda **kwargs: "journals/test.md")

    trade = orchestrator._execute_trade(
        cycle_id="cycle_t",
        decision={"conviction": 80, "primary_strategy": "momentum", "stop_loss_pct": -8.0, "reasoning": "ok"},
        action="BUY",
        ticker="AAPL_US_EQ",
        final_alloc=5.0,
        current_value=10_000,
        cash_gbp=5_000,
        total_return_pct=0.0,
        alpha_pct=0.0,
        existing_tickers=set(),
        market_regime="BULL",
        vix=18,
        macro={"sp500_pct_above_200ma": 5.0},
        stocks_data=[{"ticker": "AAPL_US_EQ", "indicators": {"current_price": 10}, "fundamentals": {}}],
        analyst_data_map={},
        av_broad_sentiment={},
        mod_result=DummyMod(),
        risk_verdict=DummyRisk(),
    )

    assert trade is not None
    assert len(notifications.execution_payloads) == 1
    assert notifications.execution_payloads[0]["execution_status"] == "dry_run"


def test_state_machine_transition_emits_notification(monkeypatch) -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    if DashboardBase is not None:
        DashboardBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def _session_factory():
        return Session()

    monkeypatch.setattr("src.orchestrator.state_machine.get_session", _session_factory)

    sm = StateMachine()
    notifications = CaptureNotifications()
    sm.notification_service = notifications

    sm.transition("CAUTIOUS", "drawdown reached")

    assert len(notifications.state_payloads) == 1
    assert notifications.state_payloads[0]["new_state"] == "CAUTIOUS"


def test_scheduler_exception_emits_critical(monkeypatch) -> None:
    from src.scheduler import scheduler

    notifications = CaptureNotifications()

    class FakeNotificationService:
        def __init__(self):
            pass

        def emit_critical_cycle_failure(self, *, cycle_id, payload, source="scheduler") -> None:
            notifications.critical_payloads.append(payload)

    class FakeOrchestrator:
        def __init__(self, dry_run=False):
            pass

        def run_cycle(self):
            raise RuntimeError("boom")

        def close(self):
            return

    monkeypatch.setattr("src.agents.notifications.NotificationService", FakeNotificationService)
    monkeypatch.setattr("src.orchestrator.main.Orchestrator", FakeOrchestrator)

    scheduler._run_analysis_cycle()

    assert len(notifications.critical_payloads) == 1
    assert notifications.critical_payloads[0]["error_type"] == "RuntimeError"
