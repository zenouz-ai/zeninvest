"""Unit tests for completed-trade timeline review helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.agents.reporting.outcome_classification import (
    EXIT_REASON_TRAILING_STOP,
    derive_label_3class,
    exit_label,
    infer_exit_reason,
    simple_result,
)
from src.agents.reporting.trade_review import (
    build_timeline_window,
    build_trade_timeline,
    fifo_buy_legs_for_sell,
    load_research_payload,
    match_strategy_decision,
)
from src.data.models import Base, Order, ResearchLog, StopLossAdjustment, StrategyDecision, TradeOutcome


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_build_timeline_window_caps_at_now():
    buy = datetime(2025, 1, 1, tzinfo=timezone.utc)
    sell = datetime(2025, 6, 1, tzinfo=timezone.utc)
    now = datetime(2025, 12, 1, tzinfo=timezone.utc)
    window = build_timeline_window(buy, sell, now=now)
    assert window.start == buy - timedelta(days=180)
    assert window.end == sell + timedelta(days=60)


def test_build_timeline_window_recent_sell_uses_now():
    buy = datetime(2025, 5, 1, tzinfo=timezone.utc)
    sell = datetime(2025, 6, 1, tzinfo=timezone.utc)
    now = datetime(2025, 6, 15, tzinfo=timezone.utc)
    window = build_timeline_window(buy, sell, now=now)
    assert window.end == now


def test_match_strategy_decision_prefers_nearest_buy(db_session):
    ts = datetime(2025, 3, 10, 12, 0, tzinfo=timezone.utc)
    near = StrategyDecision(
        timestamp=datetime(2025, 3, 10, 11, 30),
        cycle_id="c1",
        ticker="BAC_US_EQ",
        action="BUY",
        reasoning="Near buy thesis",
        primary_strategy="momentum",
    )
    far = StrategyDecision(
        timestamp=datetime(2025, 3, 9, 12, 0),
        cycle_id="c0",
        ticker="BAC_US_EQ",
        action="BUY",
        reasoning="Far buy thesis",
    )
    db_session.add_all([near, far])
    db_session.commit()

    matched = match_strategy_decision(db_session, "BAC_US_EQ", ts, "BUY")
    assert matched is not None
    assert matched.cycle_id == "c1"


def test_infer_exit_reason_hard_stop_when_losing():
    sell_ts = datetime(2025, 4, 1, 15, 0, tzinfo=timezone.utc)
    stops = [{"timestamp": sell_ts, "status": "filled", "trigger_reason": "trailing_ratchet"}]
    assert (
        infer_exit_reason(
            sell_timestamp=sell_ts,
            buy_warning_note=None,
            stop_adjustments=stops,
            pnl_pct=-3.0,
        )
        == "hard_stop"
    )


def test_infer_exit_reason_stagnation():
    sell_ts = datetime(2025, 4, 1, tzinfo=timezone.utc)
    assert (
        infer_exit_reason(
            sell_timestamp=sell_ts,
            buy_warning_note="stagnation exit candidate",
            stop_adjustments=[],
        )
        == "stagnation_exit"
    )


def test_derive_label_3class_big_winner():
    assert derive_label_3class(pnl_pct=12.0, holding_days=8.0, exit_reason="manual_or_strategy") == "big_winner"
    assert derive_label_3class(pnl_pct=12.0, holding_days=20.0, exit_reason="manual_or_strategy") == "big_winner"


def test_derive_label_3class_hard_stop_is_big_loser():
    assert derive_label_3class(pnl_pct=-8.0, holding_days=5.0, exit_reason="hard_stop") == "big_loser"


def test_simple_result_and_exit_label():
    assert simple_result(5.0) == "win"
    assert simple_result(-3.0) == "loss"
    assert simple_result(0.2) == "flat"
    assert exit_label("hard_stop") == "Stop loss exit"
    assert exit_label("manual_or_strategy", sell_order_type="market") == "Market / strategy exit"


def test_load_research_payload(db_session):
    db_session.add(
        ResearchLog(
            cycle_id="cycle-r1",
            member="strategy",
            ticker="AAPL_US_EQ",
            tool_name="web_search",
            query="AAPL guidance",
            num_results=2,
            provider="brave",
            cost_usd=0.005,
            cache_hit=False,
        )
    )
    db_session.commit()
    payload = load_research_payload(db_session, "cycle-r1", "AAPL_US_EQ")
    assert payload is not None
    assert payload["summary"]["total_calls"] == 1
    assert payload["calls"][0]["member"] == "strategy"


def test_build_trade_timeline_integration(db_session, monkeypatch):
    buy_ts = datetime(2025, 1, 15, 10, 0)
    sell_ts = datetime(2025, 3, 15, 10, 0)
    buy_order = Order(
        timestamp=buy_ts,
        ticker="BAC_US_EQ",
        action="BUY",
        order_type="market",
        quantity=10.0,
        price=35.0,
        value_gbp=350.0,
        status="filled",
        strategy="momentum",
        conviction=80,
    )
    sell_order = Order(
        timestamp=sell_ts,
        ticker="BAC_US_EQ",
        action="SELL",
        order_type="market",
        quantity=-10.0,
        price=38.5,
        value_gbp=385.0,
        status="filled",
    )
    db_session.add_all([buy_order, sell_order])
    db_session.flush()

    buy_decision = StrategyDecision(
        timestamp=buy_ts,
        cycle_id="cycle-buy",
        ticker="BAC_US_EQ",
        action="BUY",
        reasoning="Strong momentum breakout",
        primary_strategy="momentum",
        conviction=80,
    )
    sell_decision = StrategyDecision(
        timestamp=sell_ts,
        cycle_id="cycle-sell",
        ticker="BAC_US_EQ",
        action="SELL",
        reasoning="Take profit on target",
        primary_strategy="momentum",
    )
    outcome = TradeOutcome(
        buy_order_id=buy_order.id,
        sell_order_id=sell_order.id,
        ticker="BAC_US_EQ",
        buy_timestamp=buy_ts,
        sell_timestamp=sell_ts,
        holding_days=59.0,
        buy_value_gbp=350.0,
        sell_value_gbp=385.0,
        pnl_gbp=35.0,
        pnl_pct=10.0,
        conviction=80,
        strategy="momentum",
    )
    db_session.add_all([buy_decision, sell_decision, outcome])
    db_session.commit()

    import pandas as pd

    fake_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-01"]),
            "open": [34.0, 35.0, 37.0],
            "high": [35.0, 36.0, 38.0],
            "low": [33.0, 34.0, 36.0],
            "close": [34.5, 35.5, 37.5],
            "volume": [1000, 1100, 1200],
        }
    )

    def _fake_fetch(tickers, start, end):
        return {"BAC": fake_df}

    monkeypatch.setattr("src.agents.reporting.trade_review.fetch_bars_yfinance", _fake_fetch)

    payload = build_trade_timeline(db_session, outcome.id)
    assert payload is not None
    assert payload["ticker"] == "BAC_US_EQ"
    assert len(payload["prices"]) == 3
    assert payload["buy"]["reasoning"] == "Strong momentum breakout"
    assert payload["sell"]["reasoning"] == "Take profit on target"
    assert payload["outcome"]["result"] == "win"
    assert payload["outcome"]["label_3class"] == "stall"
    assert payload["classification_rules"]["success_min_profit_per_day_pct"] == 0.25
    assert len(payload["buys"]) == 1


def test_build_trade_timeline_profitable_stop_exit(db_session, monkeypatch):
    """SCGLY-style: GBP win via trailing stop while USD quote fell."""
    buy_ts = datetime(2026, 4, 17, 10, 0)
    sell_ts = datetime(2026, 6, 8, 10, 0)
    buy_order = Order(
        timestamp=buy_ts,
        ticker="SCGLY_US_EQ",
        action="BUY",
        order_type="market",
        quantity=24.0,
        price=17.49,
        value_gbp=303.39,
        status="filled",
        strategy="factor",
        conviction=82,
    )
    sell_order = Order(
        timestamp=sell_ts,
        ticker="SCGLY_US_EQ",
        action="SELL",
        order_type="stop",
        quantity=-24.0,
        price=16.09,
        value_gbp=386.16,
        status="filled",
    )
    db_session.add_all([buy_order, sell_order])
    db_session.flush()
    db_session.add(
        StopLossAdjustment(
            timestamp=sell_ts,
            ticker="SCGLY_US_EQ",
            adjustment_type="trailing",
            trigger_reason="trailing_ratchet",
            status="filled",
            old_stop_price=15.0,
            new_stop_price=16.0,
        )
    )
    outcome = TradeOutcome(
        buy_order_id=buy_order.id,
        sell_order_id=sell_order.id,
        ticker="SCGLY_US_EQ",
        buy_timestamp=buy_ts,
        sell_timestamp=sell_ts,
        holding_days=51.9,
        buy_value_gbp=303.39,
        sell_value_gbp=386.16,
        pnl_gbp=82.77,
        pnl_pct=27.3,
        conviction=82,
        strategy="factor",
    )
    db_session.add(outcome)
    db_session.commit()

    import pandas as pd

    fake_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-17", "2026-06-08"]),
            "close": [17.49, 16.09],
        }
    )
    monkeypatch.setattr(
        "src.agents.reporting.trade_review.fetch_bars_yfinance",
        lambda *args, **kwargs: {"SCGLY": fake_df},
    )

    payload = build_trade_timeline(db_session, outcome.id)
    assert payload is not None
    assert payload["outcome"]["result"] == "win"
    assert payload["outcome"]["label_3class"] == "big_winner"
    assert payload["outcome"]["exit_reason"] == EXIT_REASON_TRAILING_STOP
    assert payload["outcome"]["quote_return_pct"] == pytest.approx(-8.0, abs=0.1)


def test_build_trade_timeline_multiple_buys(db_session, monkeypatch):
    buy1_ts = datetime(2026, 5, 8, 14, 9)
    buy2_ts = datetime(2026, 5, 12, 16, 40)
    sell_ts = datetime(2026, 6, 5, 13, 52)
    buy1 = Order(
        timestamp=buy1_ts,
        ticker="IHG_US_EQ",
        action="BUY",
        order_type="market",
        quantity=2.0,
        decision_price=150.85,
        value_gbp=295.6467,
        status="filled",
        strategy="momentum",
        conviction=90,
    )
    buy2 = Order(
        timestamp=buy2_ts,
        ticker="IHG_US_EQ",
        action="BUY",
        order_type="market",
        quantity=1.0,
        decision_price=149.76,
        value_gbp=200.0,
        status="filled",
        strategy="momentum",
        conviction=88,
    )
    sell = Order(
        timestamp=sell_ts,
        ticker="IHG_US_EQ",
        action="SELL",
        order_type="market",
        quantity=-3.0,
        decision_price=162.96,
        value_gbp=364.718694079107,
        status="filled",
    )
    db_session.add_all([buy1, buy2, sell])
    db_session.flush()

    db_session.add_all([
        StrategyDecision(
            timestamp=buy1_ts,
            cycle_id="cycle-buy-1",
            ticker="IHG_US_EQ",
            action="BUY",
            reasoning="First momentum entry",
            primary_strategy="momentum",
        ),
        StrategyDecision(
            timestamp=buy2_ts,
            cycle_id="cycle-buy-2",
            ticker="IHG_US_EQ",
            action="BUY",
            reasoning="Scale-in add",
            primary_strategy="momentum",
        ),
    ])
    outcome = TradeOutcome(
        buy_order_id=buy1.id,
        sell_order_id=sell.id,
        ticker="IHG_US_EQ",
        buy_timestamp=buy1_ts,
        sell_timestamp=sell_ts,
        holding_days=28.0,
        buy_value_gbp=495.6467,
        sell_value_gbp=364.718694079107,
        pnl_gbp=-130.928005920893,
        pnl_pct=-26.4155911702616,
        conviction=90,
        strategy="momentum",
    )
    db_session.add(outcome)
    db_session.commit()

    legs = fifo_buy_legs_for_sell(db_session, sell)
    assert len(legs) == 2
    assert legs[0].quantity_matched == 2.0
    assert legs[1].quantity_matched == 1.0

    import pandas as pd

    fake_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-05-08", "2026-05-12", "2026-06-05"]),
            "open": [149.0, 150.0, 162.0],
            "high": [151.0, 151.0, 163.0],
            "low": [148.0, 149.0, 161.0],
            "close": [149.62, 150.38, 162.15],
            "volume": [1000, 1100, 1200],
        }
    )
    monkeypatch.setattr(
        "src.agents.reporting.trade_review.fetch_bars_yfinance",
        lambda *args, **kwargs: {"IHG": fake_df},
    )

    payload = build_trade_timeline(db_session, outcome.id)
    assert payload is not None
    assert len(payload["buys"]) == 2
    assert payload["buys"][0]["reasoning"] == "First momentum entry"
    assert payload["buys"][1]["reasoning"] == "Scale-in add"
    assert payload["buys"][0]["decision_price"] == 150.85
    assert payload["buys"][1]["value_gbp"] == 200.0
    assert payload["outcome"]["cost_basis_gbp"] == 495.6467
    assert payload["outcome"]["result"] == "loss"
