"""End-to-end orchestrator integration coverage for US-7.4."""

from types import SimpleNamespace
from types import MethodType

from dashboard.backend.app.database import Run

from src.data.models import ModerationLog, Order, RiskDecision, StrategyDecision


def test_run_cycle_dry_run_records_full_decision_chain(
    orchestrator_test_harness,
    orchestrator_db_session,
):
    orchestrator_test_harness.seed_state()
    orchestrator = orchestrator_test_harness.build_orchestrator(
        dry_run=True,
        decisions=[
            {
                "ticker": "AAPL_US_EQ",
                "action": "BUY",
                "target_allocation_pct": 6.0,
                "conviction": 84,
                "primary_strategy": "momentum",
                "reasoning": "Breakout with strong breadth",
                "growth_potential": "HIGH",
                "risk_level": "MEDIUM",
                "catalysts": ["AI demand"],
                "risks": ["Valuation"],
                "exit_conditions": "Momentum breakdown",
                "upside_target_pct": 14.0,
                "stop_loss_pct": 0.0,
                "expected_holding_period": "3 months",
                "news_sentiment_summary": "Positive",
            },
            {
                "ticker": "MSFT_US_EQ",
                "action": "HOLD",
                "target_allocation_pct": 0.0,
                "conviction": 0,
                "primary_strategy": "factor",
                "reasoning": "No edge this cycle",
            },
        ],
    )

    result = orchestrator.run_cycle()

    orchestrator_db_session.expire_all()

    run = orchestrator_db_session.query(Run).filter(Run.cycle_id == result["cycle_id"]).one()
    strategy_rows = orchestrator_db_session.query(StrategyDecision).filter(
        StrategyDecision.cycle_id == result["cycle_id"]
    ).all()
    moderation_rows = orchestrator_db_session.query(ModerationLog).filter(
        ModerationLog.cycle_id == result["cycle_id"]
    ).all()
    risk_rows = orchestrator_db_session.query(RiskDecision).filter(
        RiskDecision.cycle_id == result["cycle_id"]
    ).all()
    orders = orchestrator_db_session.query(Order).all()

    assert result["status"] == "completed"
    assert result.get("orphaned_decisions") is None
    assert len(result["trades"]) == 1
    assert len(result["rejected_stocks"]) == 1
    assert result["rejected_stocks"][0]["ticker"] == "MSFT_US_EQ"
    assert result["rejected_stocks"][0]["stage"] == "strategy_hold"
    assert result["trades"][0]["ticker"] == "AAPL_US_EQ"
    assert result["trades"][0]["execution"]["status"] == "dry_run"

    assert run.status == "completed"
    assert run.run_type == "dry_run"
    assert run.summary_json["num_trades"] == 1
    assert run.summary_json["num_rejected"] == 1

    assert {row.ticker for row in strategy_rows} == {"AAPL_US_EQ", "MSFT_US_EQ"}
    assert len(moderation_rows) == 3
    assert {row.moderator for row in moderation_rows} == {"strategy", "gpt-4o", "gemini-2.0-flash"}
    assert len(risk_rows) == 1
    assert risk_rows[0].ticker == "AAPL_US_EQ"
    assert risk_rows[0].verdict == "APPROVE"
    assert len(orders) == 1
    assert orders[0].ticker == "AAPL_US_EQ"
    assert orders[0].action == "BUY"
    assert orders[0].status == "dry_run"


def test_run_cycle_surfaces_orphaned_strategy_decisions(
    orchestrator_test_harness,
):
    orchestrator_test_harness.seed_state()
    orchestrator = orchestrator_test_harness.build_orchestrator(
        dry_run=True,
        decisions=[
            {
                "ticker": "AAPL_US_EQ",
                "action": "BUY",
                "target_allocation_pct": 6.0,
                "conviction": 84,
                "primary_strategy": "momentum",
                "reasoning": "Breakout with strong breadth",
            },
        ],
    )
    orchestrator._execute_trade = lambda **kwargs: None

    result = orchestrator.run_cycle()

    assert result["status"] == "completed"
    assert result["trades"] == []
    assert result["rejected_stocks"] == []
    assert result["orphaned_decisions"] == ["AAPL_US_EQ"]


def test_live_hold_cancels_stale_pending_market_sell(
    orchestrator_test_harness,
):
    orchestrator_test_harness.seed_state()
    orchestrator = orchestrator_test_harness.build_orchestrator(
        dry_run=False,
        decisions=[
            {
                "ticker": "ORCL_US_EQ",
                "action": "HOLD",
                "target_allocation_pct": 0.0,
                "conviction": 55,
                "primary_strategy": "momentum",
                "reasoning": "Too early to abandon thesis this cycle",
            },
        ],
        stocks_data=[
            {
                "ticker": "ORCL_US_EQ",
                "name": "Oracle Corp.",
                "relative_strength_6m": 40.0,
                "six_month_return": -0.08,
                "ohlcv": {"close": [150 - idx * 0.1 for idx in range(90)]},
                "indicators": {
                    "current_price": 146.0,
                    "close_prices": [150 - idx * 0.1 for idx in range(90)],
                    "rsi": 44.0,
                    "macd": -0.8,
                    "atr": 3.2,
                },
                "fundamentals": {
                    "sector": "Technology",
                    "industry": "Software",
                    "market_cap": 1_000_000_000_000,
                    "business_summary": "Oracle summary",
                    "trailing_pe": 24.0,
                    "pb_ratio": 6.2,
                    "roe": 0.28,
                    "profit_margin": 0.23,
                    "debt_equity": 0.5,
                    "earnings_growth": 0.12,
                },
            }
        ],
    )

    cancel_calls: list[tuple[str, str]] = []
    orchestrator._order_manager = SimpleNamespace(
        sync_order_status_from_t212=lambda: 0,
        liquidate_all=lambda: {"status": "ok", "orders": []},
        cancel_pending_market_sells=lambda ticker, reason: (
            cancel_calls.append((ticker, reason)) or {"status": "ok", "cancelled": ["sell-live-1"]}
        ),
    )

    result = orchestrator.run_cycle()

    assert result["status"] == "completed"
    assert len(cancel_calls) == 1
    assert cancel_calls[0][0] == "ORCL_US_EQ"
    assert "newer HOLD decision" in cancel_calls[0][1]


def test_risk_parity_runs_before_moderation_and_persists_adjusted_target(
    orchestrator_test_harness,
    orchestrator_db_session,
    monkeypatch,
):
    orchestrator_test_harness.seed_state()
    stocks_data = [
        {
            "ticker": "AAPL_US_EQ",
            "name": "Apple Inc.",
            "relative_strength_6m": 72.0,
            "six_month_return": 0.18,
            "ohlcv": {"close": [100 + idx for idx in range(90)]},
            "indicators": {
                "current_price": 190.0,
                "close_prices": [100 + idx for idx in range(90)],
                "rsi": 56.0,
                "macd": 1.2,
                "atr": 4.5,
            },
            "fundamentals": {
                "sector": "Technology",
                "industry": "Software",
                "market_cap": 1_000_000_000_000,
                "business_summary": "Apple summary",
                "trailing_pe": 24.0,
                "pb_ratio": 6.2,
                "roe": 0.28,
                "profit_margin": 0.23,
                "debt_equity": 0.5,
                "earnings_growth": 0.12,
            },
        }
    ]
    orchestrator = orchestrator_test_harness.build_orchestrator(
        dry_run=True,
        decisions=[
            {
                "ticker": "AAPL_US_EQ",
                "action": "BUY",
                "target_allocation_pct": 10.0,
                "conviction": 84,
                "primary_strategy": "momentum",
                "reasoning": "Breakout with strong breadth",
                "growth_potential": "HIGH",
                "risk_level": "MEDIUM",
                "catalysts": ["AI demand"],
                "risks": ["Valuation"],
                "exit_conditions": "Momentum breakdown",
                "upside_target_pct": 14.0,
                "stop_loss_pct": 0.0,
                "expected_holding_period": "3 months",
                "news_sentiment_summary": "Positive",
            },
        ],
        stocks_data=stocks_data,
    )
    monkeypatch.setitem(orchestrator.settings._config["risk"], "risk_parity_enabled", True)
    monkeypatch.setitem(orchestrator.settings._config["risk"], "risk_parity_target_vol", 1.0)
    monkeypatch.setitem(orchestrator.settings._config["risk"], "max_single_stock_pct", 80.0)
    monkeypatch.setitem(orchestrator.settings._config["trading"], "cash_floor_pct", 0.0)

    captured = {}
    original_review_trade = orchestrator.moderation_panel.review_trade

    def wrapped_review_trade(self, **kwargs):
        captured["moderation_target_pct"] = kwargs["trade_proposal"].get("target_allocation_pct")
        return original_review_trade(**kwargs)

    orchestrator.moderation_panel.review_trade = MethodType(wrapped_review_trade, orchestrator.moderation_panel)

    result = orchestrator.run_cycle()

    orchestrator_db_session.expire_all()
    strategy_row = orchestrator_db_session.query(StrategyDecision).filter(
        StrategyDecision.cycle_id == result["cycle_id"],
        StrategyDecision.ticker == "AAPL_US_EQ",
    ).one()
    risk_row = orchestrator_db_session.query(RiskDecision).filter(
        RiskDecision.cycle_id == result["cycle_id"],
        RiskDecision.ticker == "AAPL_US_EQ",
    ).one()

    assert result["status"] == "completed"
    assert strategy_row.target_allocation_pct == 10.0
    assert strategy_row.risk_parity_target_allocation_pct is not None
    assert strategy_row.risk_parity_trailing_vol_pct is not None
    assert strategy_row.risk_parity_applied is True
    assert captured["moderation_target_pct"] == strategy_row.risk_parity_target_allocation_pct
    assert risk_row.proposed_allocation_pct == strategy_row.risk_parity_target_allocation_pct


def test_buy_execution_uses_delta_to_target_for_existing_holding(
    orchestrator_test_harness,
    orchestrator_db_session,
    monkeypatch,
):
    orchestrator_test_harness.seed_state()
    portfolio_data = {
        "cash": 7_000.0,
        "total_value": 10_000.0,
        "invested": 3_000.0,
        "positions": [
            {
                "ticker": "AAPL_US_EQ",
                "quantity": 10.0,
                "currentPrice": 300.0,
                "value_gbp": 3_000.0,
                "pnl_gbp": 150.0,
                "pnl_pct": 5.0,
            }
        ],
        "num_positions": 1,
        "daily_pnl_pct": 0.0,
        "total_return_pct": 0.0,
        "alpha_pct": 0.0,
    }
    stocks_data = [
        {
            "ticker": "AAPL_US_EQ",
            "name": "Apple Inc.",
            "relative_strength_6m": 72.0,
            "six_month_return": 0.18,
            "ohlcv": {"close": [100 + idx for idx in range(90)]},
            "indicators": {
                "current_price": 100.0,
                "close_prices": [100 + idx for idx in range(90)],
                "rsi": 56.0,
                "macd": 1.2,
                "atr": 4.5,
            },
            "fundamentals": {
                "sector": "Technology",
                "industry": "Software",
                "market_cap": 1_000_000_000_000,
                "business_summary": "Apple summary",
                "trailing_pe": 24.0,
                "pb_ratio": 6.2,
                "roe": 0.28,
                "profit_margin": 0.23,
                "debt_equity": 0.5,
                "earnings_growth": 0.12,
            },
        }
    ]
    orchestrator = orchestrator_test_harness.build_orchestrator(
        dry_run=True,
        portfolio_data=portfolio_data,
        decisions=[
            {
                "ticker": "AAPL_US_EQ",
                "action": "BUY",
                "target_allocation_pct": 40.0,
                "conviction": 84,
                "primary_strategy": "momentum",
                "reasoning": "Add to winner",
                "growth_potential": "HIGH",
                "risk_level": "MEDIUM",
                "stop_loss_pct": 0.0,
            },
        ],
        stocks_data=stocks_data,
    )
    monkeypatch.setitem(orchestrator.settings._config["risk"], "risk_parity_enabled", False)
    monkeypatch.setitem(orchestrator.settings._config["risk"], "max_single_stock_pct", 50.0)
    monkeypatch.setitem(orchestrator.settings._config["risk"], "max_sector_pct", 100.0)

    result = orchestrator.run_cycle()

    order = orchestrator_db_session.query(Order).filter(Order.ticker == "AAPL_US_EQ").one()

    assert result["status"] == "completed"
    assert order.value_gbp == 1000.0
    assert result["trades"][0]["execution"]["value_gbp"] == 1000.0


def test_risk_parity_disabled_preserves_current_target_and_null_metadata(
    orchestrator_test_harness,
    orchestrator_db_session,
    monkeypatch,
):
    orchestrator_test_harness.seed_state()
    orchestrator = orchestrator_test_harness.build_orchestrator(
        dry_run=True,
        decisions=[
            {
                "ticker": "AAPL_US_EQ",
                "action": "BUY",
                "target_allocation_pct": 10.0,
                "conviction": 84,
                "primary_strategy": "momentum",
                "reasoning": "Breakout with strong breadth",
            },
        ],
    )
    monkeypatch.setitem(orchestrator.settings._config["risk"], "risk_parity_enabled", False)

    result = orchestrator.run_cycle()

    strategy_row = orchestrator_db_session.query(StrategyDecision).filter(
        StrategyDecision.cycle_id == result["cycle_id"],
        StrategyDecision.ticker == "AAPL_US_EQ",
    ).one()
    risk_row = orchestrator_db_session.query(RiskDecision).filter(
        RiskDecision.cycle_id == result["cycle_id"],
        RiskDecision.ticker == "AAPL_US_EQ",
    ).one()

    assert strategy_row.target_allocation_pct == 10.0
    assert strategy_row.risk_parity_target_allocation_pct is None
    assert strategy_row.risk_parity_trailing_vol_pct is None
    assert strategy_row.risk_parity_applied is None
    assert risk_row.proposed_allocation_pct == 10.0
