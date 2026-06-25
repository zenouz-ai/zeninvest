"""Shared pytest fixtures for orchestrator integration coverage."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.agents.execution.order_manager import OrderManager
from src.data.models import Base, SystemState
from src.orchestrator.main import Orchestrator
from src.orchestrator.state_machine import StateMachine
from src.utils.cost_tracker import DegradationLevel

try:
    from dashboard.backend.app.database import Base as DashboardBase
except ImportError:  # pragma: no cover - dashboard always present in repo
    DashboardBase = None


PATCHED_GET_SESSION_TARGETS = [
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
    "src.learning.export.get_session",
]


class _NoopNotifications:
    """Fail-open notification stub for orchestration tests."""

    def emit_cycle_run_summary(self, **kwargs) -> None:
        return None

    def emit_state_transition(self, **kwargs) -> None:
        return None

    def emit_trade_instruction_approved(self, **kwargs) -> None:
        return None

    def emit_trade_execution_result(self, **kwargs) -> None:
        return None

    def emit_trade_without_stop(self, **kwargs) -> None:
        return None

    def emit_order_adjustment(self, **kwargs) -> None:
        return None

    def emit_critical_cycle_failure(self, **kwargs) -> None:
        return None


class _FakeAlphaVantage:
    def get_broad_market_sentiment(self) -> dict:
        return {}

    def get_market_news_sentiment(self, **kwargs) -> dict:
        return {"error": "disabled"}


class _FakeDataFetcher:
    def __init__(self, macro: dict | None = None) -> None:
        self._macro = macro or {"vix": 18.0, "market_regime": "BULL"}
        self.alpha_vantage = _FakeAlphaVantage()

    def get_macro_data(self) -> dict:
        return self._macro

    def get_cached_news_sentiment(self, ticker, source, data_type):  # noqa: ANN001
        return None

    def cache_news_sentiment(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def get_analyst_data_cached(self, ticker: str) -> dict:
        return {}

    def close(self) -> None:
        return None


def _make_stock(
    ticker: str,
    *,
    name: str,
    current_price: float,
    sector: str = "Technology",
    industry: str = "Software",
) -> dict:
    close_prices = [round(current_price * (0.70 + 0.005 * idx), 2) for idx in range(90)]
    return {
        "ticker": ticker,
        "name": name,
        "relative_strength_6m": 72.0,
        "six_month_return": 0.18,
        "ohlcv": {"close": close_prices},
        "indicators": {
            "current_price": current_price,
            "close_prices": close_prices,
            "rsi": 56.0,
            "macd": 1.2,
            "atr": 4.5,
        },
        "fundamentals": {
            "sector": sector,
            "industry": industry,
            "market_cap": 1_000_000_000_000,
            "business_summary": f"{name} summary",
            "trailing_pe": 24.0,
            "pb_ratio": 6.2,
            "roe": 0.28,
            "profit_margin": 0.23,
            "debt_equity": 0.5,
            "earnings_growth": 0.12,
        },
    }


def _build_sub_results(stocks_data: list[dict], decisions: list[dict]) -> dict:
    buy_tickers = {
        str(decision.get("ticker", "")).upper()
        for decision in decisions
        if str(decision.get("action", "")).upper() == "BUY"
    }

    momentum = []
    mean_reversion = []
    factor = []
    top_factor = []

    for stock in stocks_data:
        ticker = stock["ticker"]
        is_buy = ticker in buy_tickers
        momentum.append(
            SimpleNamespace(
                ticker=ticker,
                action="BUY" if is_buy else "HOLD",
                score=82 if is_buy else 38,
                reasoning="Momentum confirms upside" if is_buy else "No strong momentum edge",
            )
        )
        mean_reversion.append(
            SimpleNamespace(
                ticker=ticker,
                action="HOLD",
                score=35,
                reasoning="No mean-reversion setup",
            )
        )
        factor_score = SimpleNamespace(
            ticker=ticker,
            composite_score=76 if is_buy else 61,
            value_score=58,
            quality_score=81,
            momentum_score=74 if is_buy else 55,
            reasoning="Composite factor score",
        )
        factor.append(factor_score)
        if is_buy:
            top_factor.append(factor_score)

    return {
        "momentum": momentum,
        "mean_reversion": mean_reversion,
        "factor": factor,
        "top_factor": top_factor,
    }


class OrchestratorTestHarness:
    """Reusable orchestrator builder for end-to-end integration tests."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, db_session) -> None:
        self.monkeypatch = monkeypatch
        self.db_session = db_session
        self._patch_shared_runtime()

    def _patch_shared_runtime(self) -> None:
        self.monkeypatch.setattr("src.orchestrator.main.get_cost_summary", lambda days=1: {})
        self.monkeypatch.setattr("src.orchestrator.main.get_degradation_level", lambda: DegradationLevel.FULL)
        self.monkeypatch.setattr("src.orchestrator.main.log_event", lambda *args, **kwargs: None)
        self.monkeypatch.setattr("src.orchestrator.main.DASHBOARD_AVAILABLE", True)
        self.monkeypatch.setattr("src.orchestrator.main.generate_trade_journal", lambda **kwargs: "/tmp/test_journal.md")
        self.monkeypatch.setattr("src.orchestrator.main.update_trade_outcomes", lambda: None)
        self.monkeypatch.setattr("src.orchestrator.main.update_performance_metrics", lambda: None)
        self.monkeypatch.setattr("dashboard.backend.app.database.init_dashboard_tables", lambda: None)
        self.monkeypatch.setattr(
            "dashboard.backend.app.services.event_logger.flush_events",
            lambda timeout_seconds=2.0: None,
        )
        self.monkeypatch.setattr("src.agents.execution.order_manager.log_event", lambda *args, **kwargs: None)
        self.monkeypatch.setattr("src.agents.moderation.panel.get_degradation_level", lambda: DegradationLevel.FULL)
        self.monkeypatch.setattr(
            "src.agents.moderation.openai_mod.review_trade",
            lambda *args, **kwargs: {
                "available": True,
                "verdict": "AGREE",
                "reasoning": "Skeptic agrees with the trade",
                "score": 8,
            },
        )
        self.monkeypatch.setattr(
            "src.agents.moderation.gemini_mod.review_trade",
            lambda *args, **kwargs: {
                "available": True,
                "moderator": "gemini-2.0-flash",
                "verdict": "AGREE",
                "assessment": "Risk profile acceptable",
                "growth_score": 8,
                "risk_score": 4,
                "confidence_score": 9,
            },
        )

    def seed_state(
        self,
        *,
        state: str = "ACTIVE",
        peak_portfolio_value: float = 10_000.0,
        current_drawdown_pct: float = 0.0,
        paused: bool = False,
    ) -> SystemState:
        self.db_session.query(SystemState).delete()
        system_state = SystemState(
            state=state,
            peak_portfolio_value=peak_portfolio_value,
            current_drawdown_pct=current_drawdown_pct,
            paused=paused,
        )
        self.db_session.add(system_state)
        self.db_session.commit()
        return system_state

    def build_orchestrator(
        self,
        *,
        dry_run: bool = True,
        account_type: str = "practice",
        portfolio_data: dict | None = None,
        decisions: list[dict] | None = None,
        stocks_data: list[dict] | None = None,
        macro: dict | None = None,
    ) -> Orchestrator:
        decisions = decisions or []
        stocks_data = stocks_data or [
            _make_stock("AAPL_US_EQ", name="Apple Inc.", current_price=200.0),
            _make_stock("MSFT_US_EQ", name="Microsoft Corp.", current_price=150.0),
        ]
        portfolio_data = portfolio_data or {
            "cash": 10_000.0,
            "total_value": 10_000.0,
            "invested": 0.0,
            "positions": [],
            "num_positions": 0,
            "daily_pnl_pct": 0.0,
            "total_return_pct": 0.0,
            "alpha_pct": 0.0,
        }
        sub_results = _build_sub_results(stocks_data, decisions)

        orchestrator = Orchestrator(dry_run=dry_run)
        orchestrator.notification_service = _NoopNotifications()
        orchestrator.state_machine.notification_service = _NoopNotifications()
        orchestrator.data_fetcher = _FakeDataFetcher(macro=macro)
        orchestrator.settings._config.setdefault("dashboard", {})["enabled"] = True
        orchestrator.settings._config["dashboard"]["events_enabled"] = True
        orchestrator.settings._config.setdefault("opportunity", {})["enabled"] = False
        orchestrator.settings._config.setdefault("research", {})["enabled"] = False
        orchestrator.settings._config.setdefault("order_management", {})["enabled"] = False
        orchestrator.settings._config.setdefault("trading", {})["account_type"] = account_type

        orchestrator._get_portfolio_state = lambda: portfolio_data
        orchestrator._fetch_stocks_data = (
            lambda current_positions, exclude_tickers=None, system_state="ACTIVE", cycle_id=None, **kwargs: stocks_data
        )

        def _fake_run_sub_strategies(stocks_data_arg, existing_positions):  # noqa: ANN001
            return sub_results

        def _fake_synthesize_with_claude(**kwargs):
            result = {
                "decisions": decisions,
                "market_assessment": "Constructive market backdrop",
                "portfolio_commentary": "Test portfolio commentary",
            }
            if kwargs.get("persist_decisions", True):
                orchestrator.strategy_engine._log_decisions(
                    result,
                    kwargs["cycle_id"],
                    json.dumps(result),
                )
            return result

        orchestrator.strategy_engine.run_sub_strategies = _fake_run_sub_strategies
        orchestrator.strategy_engine.synthesize_with_claude = _fake_synthesize_with_claude

        if dry_run:
            orchestrator._order_manager = OrderManager(client=MagicMock(), dry_run=True)
        else:
            orchestrator._order_manager = SimpleNamespace(
                sync_order_status_from_t212=lambda: 0,
                liquidate_all=lambda: {"status": "ok", "orders": []},
            )

        return orchestrator

    def build_state_machine(self) -> StateMachine:
        state_machine = StateMachine()
        state_machine.notification_service = _NoopNotifications()
        return state_machine


@pytest.fixture
def orchestrator_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    if DashboardBase is not None:
        DashboardBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


@pytest.fixture
def orchestrator_db_session(orchestrator_session_factory):
    session = orchestrator_session_factory()
    yield session
    session.close()


@pytest.fixture
def patch_orchestrator_get_session(orchestrator_session_factory):
    patches = []
    for target in PATCHED_GET_SESSION_TARGETS:
        try:
            active_patch = patch(target, side_effect=orchestrator_session_factory)
            active_patch.start()
            patches.append(active_patch)
        except (AttributeError, ModuleNotFoundError):
            continue
    yield
    for active_patch in patches:
        active_patch.stop()


@pytest.fixture
def orchestrator_test_harness(monkeypatch, orchestrator_db_session, patch_orchestrator_get_session):
    yield OrchestratorTestHarness(monkeypatch=monkeypatch, db_session=orchestrator_db_session)
