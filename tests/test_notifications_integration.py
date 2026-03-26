from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data.models import Base, Order, PerformanceMetric, TradeOutcome
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

    def emit_order_adjustment(self, *, cycle_id, payload, source="stop_loss_manager") -> None:
        pass

    def emit_trade_without_stop(self, *, cycle_id, payload, source="orchestrator") -> None:
        pass


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
        "src.utils.search_api_tracker.get_session",
        "dashboard.backend.app.services.event_logger.SessionLocal",
    ]
    patches = []
    event_logger_sessionmaker = sessionmaker(bind=db_session.get_bind())
    for target in targets:
        try:
            if "event_logger.SessionLocal" in target:
                p = patch(target, event_logger_sessionmaker)
            else:
                p = patch(target, return_value=db_session)
            p.start()
            patches.append(p)
        except (AttributeError, ModuleNotFoundError):
            pass
    yield
    for p in patches:
        p.stop()


@pytest.fixture(autouse=True)
def patch_runtime_cycle_lock():
    class DummyLock:
        def release(self) -> None:
            return

    with patch("src.orchestrator.main.acquire_runtime_lock", return_value=DummyLock()):
        yield


def test_orchestrator_paused_emits_cycle_summary(monkeypatch) -> None:
    orchestrator = Orchestrator(dry_run=True)
    notifications = CaptureNotifications()
    orchestrator.notification_service = notifications
    orchestrator.state_machine = SimpleNamespace(is_paused=True)

    monkeypatch.setattr("src.orchestrator.main.get_cost_summary", lambda days=1: {})

    result = orchestrator.run_cycle()

    assert result["status"] == "paused"
    assert len(notifications.summary_payloads) == 1


def test_orchestrator_emits_summary_without_pre_execution_instruction(monkeypatch) -> None:
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
    orchestrator._fetch_stocks_data = lambda current_positions, exclude_tickers=None, system_state="ACTIVE", cycle_id=None, **kwargs: [
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
        modifications = None

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
    assert notifications.instruction_payloads == []
    assert notifications.execution_payloads == []
    assert len(notifications.summary_payloads) == 1
    assert notifications.summary_payloads[0]["counts"]["broker_orders_submitted"] == 1


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


def test_execute_trade_buy_upgrades_to_minimum_order_value(monkeypatch) -> None:
    orchestrator = Orchestrator(dry_run=True)
    notifications = CaptureNotifications()
    orchestrator.notification_service = notifications

    class DummyOrderManager:
        last_kwargs: dict | None = None

        @classmethod
        def execute_market_order(cls, **kwargs):
            cls.last_kwargs = kwargs
            return {"status": "dry_run", "quantity": 5, "value_gbp": kwargs["target_amount_gbp"]}

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
        cycle_id="cycle_t_floor",
        decision={"conviction": 80, "primary_strategy": "momentum", "stop_loss_pct": -8.0, "reasoning": "ok"},
        action="BUY",
        ticker="AAPL_US_EQ",
        final_alloc=2.0,
        current_value=10_000,
        cash_gbp=5_000,
        total_return_pct=0.0,
        alpha_pct=0.0,
        existing_tickers=set(),
        market_regime="BULL",
        vix=18,
        macro={"sp500_pct_above_200ma": 5.0},
        stocks_data=[{"ticker": "AAPL_US_EQ", "indicators": {"current_price": 100}, "fundamentals": {}}],
        analyst_data_map={},
        av_broad_sentiment={},
        mod_result=DummyMod(),
        risk_verdict=DummyRisk(),
    )

    assert trade is not None
    assert DummyOrderManager.last_kwargs is not None
    assert DummyOrderManager.last_kwargs["target_amount_gbp"] == 500.0
    assert "buy_upgraded_to_min_order_value" in trade["execution_note"]


def test_run_cycle_skips_small_buy_when_minimum_order_has_no_cash(
    monkeypatch,
) -> None:
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

    decision = {
        "ticker": "AAPL_US_EQ",
        "action": "BUY",
        "conviction": 82,
        "target_allocation_pct": 2.0,
        "reasoning": "Strong trend and supportive sentiment",
        "stop_loss_pct": -8.0,
        "primary_strategy": "momentum",
        "news_sentiment_summary": "Bullish product cycle",
    }

    orchestrator.state_machine = DummyStateMachine()
    orchestrator.settings._config.setdefault("opportunity", {})["enabled"] = False
    orchestrator._get_portfolio_state = lambda: {
        "cash": 300.0,
        "total_value": 10_000.0,
        "invested": 9_700.0,
        "positions": [],
        "num_positions": 0,
        "daily_pnl_pct": 0.0,
        "total_return_pct": 0.0,
        "alpha_pct": 0.0,
    }
    orchestrator._fetch_stocks_data = lambda current_positions, exclude_tickers=None, system_state="ACTIVE", cycle_id=None, **kwargs: [
        {
            "ticker": "AAPL_US_EQ",
            "name": "Apple Inc.",
            "indicators": {"current_price": 180},
            "fundamentals": {"industry": "Consumer Electronics", "market_cap": 2_800_000_000_000},
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
        modifications = None

        @staticmethod
        def to_dict() -> dict:
            return {"consensus": "APPROVED", "gpt4o_verdict": {}, "gemini_verdict": {}}

    class DummyRisk:
        verdict = "APPROVE"
        adjusted_allocation_pct = 2.0
        triggered_rules: list[str] = []
        rules_checked: list[str] = []
        reasoning = "All checks passed"

    orchestrator.moderation_panel = SimpleNamespace(review_trade=lambda **kwargs: DummyMod())
    orchestrator.risk_manager = SimpleNamespace(
        evaluate_trade=lambda **kwargs: DummyRisk(),
        get_drawdown_state=lambda current_value, peak_value: "ACTIVE",
    )
    orchestrator._save_snapshot = lambda portfolio_data, state: None
    monkeypatch.setattr("src.orchestrator.main.get_degradation_level", lambda: DegradationLevel.FULL)
    monkeypatch.setattr("src.orchestrator.main.get_cost_summary", lambda days=1: {})

    result = orchestrator.run_cycle()

    assert result["status"] == "completed"
    assert result["trades"] == []
    assert len(result["rejected_stocks"]) == 1
    assert result["rejected_stocks"][0]["reason_code"] == "cash_floor_guard"
    assert len(notifications.instruction_payloads) == 1
    assert notifications.instruction_payloads[0]["notification_kind"] == "buy_skipped"


def test_execute_trade_reduce_converts_to_full_sell_below_floor(monkeypatch) -> None:
    orchestrator = Orchestrator(dry_run=True)
    notifications = CaptureNotifications()
    orchestrator.notification_service = notifications

    class DummyOrderManager:
        last_kwargs: dict | None = None

        @classmethod
        def execute_market_order(cls, **kwargs):
            cls.last_kwargs = kwargs
            return {
                "status": "dry_run",
                "quantity": 60,
                "value_gbp": kwargs["target_amount_gbp"],
            }

        @staticmethod
        def place_stop_loss(**kwargs):
            return {"status": "skipped"}

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
        cycle_id="cycle_reduce_floor",
        decision={"conviction": 80, "primary_strategy": "momentum", "stop_loss_pct": -8.0, "reasoning": "trim"},
        action="REDUCE",
        ticker="AAPL_US_EQ",
        final_alloc=20.0,
        current_value=1_000.0,
        cash_gbp=400.0,
        total_return_pct=0.0,
        alpha_pct=0.0,
        existing_tickers={"AAPL_US_EQ"},
        market_regime="BULL",
        vix=18,
        macro={"sp500_pct_above_200ma": 5.0},
        stocks_data=[{"ticker": "AAPL_US_EQ", "indicators": {"current_price": 10}, "fundamentals": {}}],
        analyst_data_map={},
        av_broad_sentiment={},
        mod_result=DummyMod(),
        risk_verdict=DummyRisk(),
        portfolio_data={
            "total_value": 1_000.0,
            "positions": [
                {"ticker": "AAPL_US_EQ", "value_gbp": 600.0},
            ],
        },
    )

    assert trade is not None
    assert trade["action"] == "SELL"
    assert DummyOrderManager.last_kwargs is not None
    assert DummyOrderManager.last_kwargs["action"] == "SELL"
    assert DummyOrderManager.last_kwargs["target_amount_gbp"] == pytest.approx(600.0)
    assert len(notifications.execution_payloads) == 1
    assert notifications.execution_payloads[0]["action"] == "SELL"
    assert "reduce_converted_to_sell_below_floor" in notifications.execution_payloads[0]["execution_note"]


@pytest.mark.parametrize(
    ("pnl_pct", "position_pct", "sector_pct", "expected_allow"),
    [
        (5.0, 8.0, 20.0, False),
        (12.0, 8.0, 20.0, True),
        (5.0, 21.0, 20.0, True),
        (5.0, 8.0, 45.0, True),
    ],
)
def test_reduce_guardrail_requires_gain_or_risk_breach(
    pnl_pct: float,
    position_pct: float,
    sector_pct: float,
    expected_allow: bool,
) -> None:
    orchestrator = Orchestrator(dry_run=True)

    allow, code, reason = orchestrator._evaluate_reduce_guardrail(
        ticker="AAPL_US_EQ",
        sector="Technology",
        position_context={"AAPL_US_EQ": {"pnl_pct": pnl_pct}},
        current_allocations={"AAPL_US_EQ": position_pct},
        sector_allocations={"Technology": sector_pct},
    )

    assert allow is expected_allow
    if expected_allow:
        assert code is None
        assert reason is None
    else:
        assert code == "reduce_guardrail_no_gain_or_risk"
        assert "Held instead of reducing" in reason


def test_deterministic_take_profit_override_marks_sell_and_bypasses_min_hold() -> None:
    orchestrator = Orchestrator(dry_run=True)
    decision = {
        "ticker": "AAPL_US_EQ",
        "action": "HOLD",
        "conviction": 0,
        "reasoning": "Hold for now",
    }

    orchestrator._apply_deterministic_exit_overrides(
        decisions=[decision],
        position_context={
            "AAPL_US_EQ": {
                "pnl_pct": 15.0,
                "value_gbp": 650.0,
                "held_hours": 6.0,
            }
        },
        cycle_id="scheduled_20260325_120001",
    )

    assert decision["action"] == "SELL"
    assert decision["target_allocation_pct"] == 0.0
    assert decision["deterministic_exit_reason_code"] == "take_profit_full_sell"
    assert orchestrator._should_skip_min_holding_for_decision(decision) is True


def test_small_position_cleanup_triggers_immediately_for_any_sub_threshold_holding() -> None:
    orchestrator = Orchestrator(dry_run=True)

    active_cleanup = {
        "ticker": "VRTX_US_EQ",
        "action": "HOLD",
        "conviction": 0,
        "reasoning": "No clear edge",
    }
    still_holds_above_threshold = {
        "ticker": "ROST_US_EQ",
        "action": "HOLD",
        "conviction": 0,
        "reasoning": "No clear edge",
    }
    immediate_cleanup_even_if_new = {
        "ticker": "ORCL_US_EQ",
        "action": "HOLD",
        "conviction": 0,
        "reasoning": "No clear edge",
    }

    orchestrator._apply_deterministic_exit_overrides(
        decisions=[active_cleanup],
        position_context={"VRTX_US_EQ": {"pnl_pct": 1.0, "value_gbp": 150.0, "held_hours": 30.0}},
        cycle_id="scheduled_20260325_191501",
    )
    orchestrator._apply_deterministic_exit_overrides(
        decisions=[still_holds_above_threshold],
        position_context={"ROST_US_EQ": {"pnl_pct": 1.0, "value_gbp": 250.0, "held_hours": 30.0}},
        cycle_id="scheduled_20260325_163001",
    )
    orchestrator._apply_deterministic_exit_overrides(
        decisions=[immediate_cleanup_even_if_new],
        position_context={"ORCL_US_EQ": {"pnl_pct": 1.0, "value_gbp": 150.0, "held_hours": 8.0}},
        cycle_id="scheduled_20260325_120001",
    )

    assert active_cleanup["action"] == "SELL"
    assert active_cleanup["deterministic_exit_reason_code"] == "small_position_cleanup"
    assert still_holds_above_threshold["action"] == "HOLD"
    assert immediate_cleanup_even_if_new["action"] == "SELL"
    assert immediate_cleanup_even_if_new["deterministic_exit_reason_code"] == "small_position_cleanup"


def test_run_cycle_cleanup_sell_skips_strategy_and_uses_live_quantity(monkeypatch, db_session) -> None:
    db_session.add(
        Order(
            ticker="VRTX_US_EQ",
            action="BUY",
            order_type="market",
            quantity=5,
            price=20.0,
            value_gbp=100.0,
            status="filled",
            timestamp=datetime.now(timezone.utc) - timedelta(hours=30),
        )
    )
    db_session.commit()

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
    trading_config = orchestrator.settings._config.setdefault("trading", {})
    trading_config["cycle_frequency"] = "intraday"
    trading_config["small_position_cleanup_enabled"] = True
    orchestrator.settings._config.setdefault("opportunity", {})["enabled"] = False

    orchestrator._get_portfolio_state = lambda: {
        "cash": 9850.0,
        "total_value": 10000.0,
        "invested": 150.0,
        "positions": [
                {
                    "ticker": "VRTX_US_EQ",
                    "quantity": 5,
                    "currentPrice": 30.0,
                    "averagePrice": 29.0,
                    "value_gbp": 150.0,
                    "pnl_gbp": 5.0,
                }
            ],
        "num_positions": 1,
        "daily_pnl_pct": 0.0,
        "total_return_pct": 0.0,
        "alpha_pct": 0.0,
    }

    seen_current_positions: list[str] = []

    def fake_fetch_stocks_data(current_positions, exclude_tickers=None, system_state="ACTIVE", cycle_id=None, **kwargs):
        seen_current_positions[:] = [pos["ticker"] for pos in current_positions]
        return []

    orchestrator._fetch_stocks_data = fake_fetch_stocks_data
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
        synthesize_with_claude=lambda **kwargs: {"decisions": [], "market_assessment": ""},
    )

    def unexpected_review_trade(**kwargs):
        raise AssertionError("cleanup ticker should not reach moderation")

    def unexpected_risk_trade(**kwargs):
        raise AssertionError("cleanup ticker should not reach risk")

    orchestrator.moderation_panel = SimpleNamespace(review_trade=unexpected_review_trade)
    orchestrator.risk_manager = SimpleNamespace(
        evaluate_trade=unexpected_risk_trade,
        get_drawdown_state=lambda current_value, peak_value: "ACTIVE",
    )
    orchestrator._t212_client = SimpleNamespace(get_position=lambda ticker: {"quantity": 7.0})
    orchestrator._save_snapshot = lambda portfolio_data, state: None

    captured: dict[str, float | str] = {}

    def fake_execute_trade(cycle_id, decision, action, ticker, **kwargs):
        captured["ticker"] = ticker
        captured["quantity_override"] = kwargs["quantity_override"]
        captured["moderation"] = kwargs["mod_result"].consensus
        captured["risk"] = kwargs["risk_verdict"].verdict
        return {
            "ticker": ticker,
            "action": "SELL",
            "execution": {"status": "dry_run"},
            "moderation": kwargs["mod_result"].consensus,
            "risk": kwargs["risk_verdict"].verdict,
        }

    orchestrator._execute_trade = fake_execute_trade

    monkeypatch.setattr("src.orchestrator.main.get_degradation_level", lambda: DegradationLevel.FULL)
    monkeypatch.setattr("src.orchestrator.main.get_cost_summary", lambda days=1: {})

    result = orchestrator.run_cycle(scheduled_cycle_id="scheduled_20260325_191501")

    assert result["status"] == "completed"
    assert len(result["trades"]) == 1
    assert seen_current_positions == []
    assert captured["ticker"] == "VRTX_US_EQ"
    assert captured["quantity_override"] == 7.0
    assert captured["moderation"] == "BYPASSED"
    assert captured["risk"] == "BYPASSED"


def test_scheduled_cycle_skips_live_execution_outside_regular_market_session(monkeypatch) -> None:
    orchestrator = Orchestrator(dry_run=False)
    notifications = CaptureNotifications()
    orchestrator.notification_service = notifications
    orchestrator.state_machine = SimpleNamespace(is_paused=False, current_state="ACTIVE")
    orchestrator._get_portfolio_state = lambda: (_ for _ in ()).throw(AssertionError("portfolio should not be fetched"))

    monkeypatch.setattr("src.orchestrator.main.get_degradation_level", lambda: DegradationLevel.FULL)
    monkeypatch.setattr("src.orchestrator.main.get_cost_summary", lambda days=1: {})
    monkeypatch.setattr("src.orchestrator.main.is_within_regular_market_session", lambda settings: False)

    result = orchestrator.run_cycle(scheduled_cycle_id="scheduled_20260325_120001")

    assert result["status"] == "skipped_market_closed"
    assert result["skip_reason"] == "outside_regular_market_session"
    assert notifications.summary_payloads


def test_execute_trade_emits_take_profit_reason_code(monkeypatch) -> None:
    orchestrator = Orchestrator(dry_run=True)
    notifications = CaptureNotifications()
    orchestrator.notification_service = notifications

    class DummyOrderManager:
        @staticmethod
        def execute_market_order(**kwargs):
            return {"status": "dry_run", "quantity": 2, "value_gbp": kwargs["target_amount_gbp"]}

        @staticmethod
        def place_stop_loss(**kwargs):
            return {"status": "skipped"}

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
        cycle_id="cycle_take_profit",
        decision={
            "conviction": 90,
            "primary_strategy": "factor",
            "stop_loss_pct": -8.0,
            "reasoning": "Winner reached objective",
            "deterministic_exit_reason_code": "take_profit_full_sell",
            "deterministic_exit_reason": "Deterministic take-profit SELL: unrealized gain 15.2% meets threshold",
        },
        action="SELL",
        ticker="AAPL_US_EQ",
        final_alloc=0.0,
        current_value=10_000,
        cash_gbp=5_000,
        total_return_pct=0.0,
        alpha_pct=0.0,
        existing_tickers={"AAPL_US_EQ"},
        market_regime="BULL",
        vix=18,
        macro={"sp500_pct_above_200ma": 5.0},
        stocks_data=[{"ticker": "AAPL_US_EQ", "indicators": {"current_price": 10}, "fundamentals": {}}],
        analyst_data_map={},
        av_broad_sentiment={},
        mod_result=DummyMod(),
        risk_verdict=DummyRisk(),
        portfolio_data={
            "total_value": 10_000.0,
            "positions": [{"ticker": "AAPL_US_EQ", "value_gbp": 600.0}],
        },
    )

    assert trade is not None
    assert trade["reason_code"] == "take_profit_full_sell"
    assert len(notifications.execution_payloads) == 1
    assert notifications.execution_payloads[0]["reason_code"] == "take_profit_full_sell"


def test_execute_trade_cleanup_sell_uses_quantity_override(monkeypatch) -> None:
    orchestrator = Orchestrator(dry_run=True)
    notifications = CaptureNotifications()
    orchestrator.notification_service = notifications

    class DummyOrderManager:
        last_kwargs: dict | None = None

        @classmethod
        def execute_market_order(cls, **kwargs):
            cls.last_kwargs = kwargs
            return {"status": "dry_run", "quantity": 7.0, "value_gbp": kwargs["target_amount_gbp"]}

        @staticmethod
        def place_stop_loss(**kwargs):
            return {"status": "skipped"}

    class DummyMod:
        consensus = "BYPASSED"

        @staticmethod
        def to_dict() -> dict:
            return {"consensus": "BYPASSED"}

    class DummyRisk:
        verdict = "BYPASSED"
        rules_checked: list[str] = []
        triggered_rules: list[str] = []
        reasoning = "Deterministic cleanup SELL"

    orchestrator._order_manager = DummyOrderManager()
    monkeypatch.setattr("src.orchestrator.main.generate_trade_journal", lambda **kwargs: "journals/test.md")

    trade = orchestrator._execute_trade(
        cycle_id="cycle_cleanup",
        decision={
            "conviction": 75,
            "primary_strategy": "factor",
            "stop_loss_pct": -8.0,
            "reasoning": "Cleanup triggered",
            "deterministic_exit_reason_code": "small_position_cleanup",
            "deterministic_exit_reason": "Deterministic cleanup SELL: value below threshold",
        },
        action="SELL",
        ticker="AAPL_US_EQ",
        final_alloc=0.0,
        current_value=10_000,
        cash_gbp=5_000,
        total_return_pct=0.0,
        alpha_pct=0.0,
        existing_tickers={"AAPL_US_EQ"},
        market_regime="BULL",
        vix=18,
        macro={"sp500_pct_above_200ma": 5.0},
        stocks_data=[{"ticker": "AAPL_US_EQ", "indicators": {"current_price": 10}, "fundamentals": {}}],
        analyst_data_map={},
        av_broad_sentiment={},
        mod_result=DummyMod(),
        risk_verdict=DummyRisk(),
        portfolio_data={
            "total_value": 10_000.0,
            "positions": [{"ticker": "AAPL_US_EQ", "value_gbp": 600.0}],
        },
        quantity_override=7.0,
    )

    assert trade is not None
    assert DummyOrderManager.last_kwargs is not None
    assert DummyOrderManager.last_kwargs["quantity_override"] == 7.0
    assert DummyOrderManager.last_kwargs["target_amount_gbp"] == pytest.approx(70.0)
    assert trade["display_action"] == "SELL_CLEAN_UP"
    assert trade["reason_code"] == "small_position_cleanup"
    assert len(notifications.execution_payloads) == 1
    assert notifications.execution_payloads[0]["display_action"] == "SELL_CLEAN_UP"
    assert notifications.execution_payloads[0]["reason_code"] == "small_position_cleanup"


def test_position_summary_includes_last_buy_context(db_session) -> None:
    db_session.add(
        Order(
            ticker="AAPL_US_EQ",
            action="BUY",
            order_type="market",
            quantity=10,
            price=50.0,
            value_gbp=500.0,
            status="filled",
            timestamp=datetime(2026, 3, 24, 8, 0, 0),
        )
    )
    db_session.commit()

    summary = Orchestrator._build_position_pnl_summary(
        {
            "invested": 500.0,
            "positions": [
                {
                    "ticker": "AAPL_US_EQ",
                    "quantity": 10,
                    "currentPrice": 60.0,
                    "averagePrice": 50.0,
                    "value_gbp": 600.0,
                    "pnl_gbp": 100.0,
                }
            ],
        }
    )

    assert "Entry (GBP)" in summary
    assert "Last BUY UTC" in summary
    assert "2026-03-24 08:00" in summary
    assert "AAPL_US_EQ" in summary


def test_strategy_performance_summary_uses_wide_metrics_schema(db_session) -> None:
    db_session.add(
        PerformanceMetric(
            snapshot_date=datetime(2026, 3, 25, 0, 0, 0),
            sharpe_30d=1.2,
            sortino_30d=1.7,
            max_drawdown_pct=4.5,
            win_rate_momentum=55.0,
            win_rate_mean_reversion=62.0,
            win_rate_factor=71.0,
            num_trades=21,
        )
    )
    db_session.add_all(
        [
            TradeOutcome(
                buy_order_id=1,
                sell_order_id=2,
                ticker="AAPL_US_EQ",
                buy_timestamp=datetime.now(timezone.utc) - timedelta(days=5),
                sell_timestamp=datetime.now(timezone.utc) - timedelta(days=1),
                holding_days=4.0,
                buy_value_gbp=500.0,
                sell_value_gbp=580.0,
                pnl_gbp=80.0,
                pnl_pct=16.0,
                conviction=82,
                strategy="momentum",
                moderation_result="APPROVED",
                risk_result="APPROVE",
            ),
            TradeOutcome(
                buy_order_id=3,
                sell_order_id=4,
                ticker="MSFT_US_EQ",
                buy_timestamp=datetime.now(timezone.utc) - timedelta(days=8),
                sell_timestamp=datetime.now(timezone.utc) - timedelta(days=2),
                holding_days=6.0,
                buy_value_gbp=500.0,
                sell_value_gbp=530.0,
                pnl_gbp=30.0,
                pnl_pct=6.0,
                conviction=75,
                strategy="factor",
                moderation_result="APPROVED",
                risk_result="APPROVE",
            ),
        ]
    )
    db_session.commit()

    summary = Orchestrator._build_strategy_performance_summary()

    assert "Momentum win rate: 55%" in summary
    assert "Mean Reversion win rate: 62%" in summary
    assert "Factor win rate: 71%" in summary
    assert "Total completed trades: 21" in summary
    assert "Median holding days: 5.0" in summary
    assert "Realized take-profit exits (>= 15.0% pnl): 1 in last 30d" in summary


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

        def run_cycle(self, scheduled_cycle_id=None):
            raise RuntimeError("boom")

        def close(self):
            return

    monkeypatch.setattr("src.agents.notifications.NotificationService", FakeNotificationService)
    monkeypatch.setattr("src.orchestrator.main.Orchestrator", FakeOrchestrator)

    scheduler._run_analysis_cycle()

    assert len(notifications.critical_payloads) == 1
    assert notifications.critical_payloads[0]["error_type"] == "RuntimeError"


def test_orchestrator_continues_when_moderation_modifications_is_string(monkeypatch, caplog) -> None:
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
    orchestrator._fetch_stocks_data = lambda current_positions, exclude_tickers=None, system_state="ACTIVE", cycle_id=None, **kwargs: [
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

    class DummyRisk:
        verdict = "APPROVE"
        adjusted_allocation_pct = 8
        triggered_rules: list[str] = []
        rules_checked: list[str] = []
        reasoning = "All checks passed"

    from src.agents.moderation.panel import ModerationResult

    orchestrator.moderation_panel = SimpleNamespace(
        review_trade=lambda **kwargs: ModerationResult(
            ticker="AAPL_US_EQ",
            consensus="CAUTION",
            strategy_verdict="AGREE",
            gpt4o_verdict={"verdict": "MODIFY", "modifications": "reduce allocation to 5%"},
            gemini_verdict={"verdict": "MODIFY", "modifications": {"target_allocation_pct": 4.0}},
            moderators_available=2,
            caution_flag=True,
        )
    )
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
    assert len(notifications.summary_payloads) == 1
    assert notifications.critical_payloads == []
    assert "Ignoring malformed gpt-4o modifications" in caplog.text
