"""End-to-end orchestrator integration coverage for US-7.4."""

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
