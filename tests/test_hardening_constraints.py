"""Tests for US-7.5 schema guardrails and new defaults."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.data.models import Base, ModerationLog, Order, RiskDecision, StrategyDecision, SystemState


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


def test_system_state_defaults_include_recovery_fields(session):
    state = SystemState(state="ACTIVE", paused=False)
    session.add(state)
    session.commit()
    session.refresh(state)

    assert state.halted_recovery_streak == 0
    assert state.peak_inflation_warning_note is None


def test_order_constraint_rejects_buy_with_negative_quantity(session):
    session.add(
        Order(
            ticker="AAPL_US_EQ",
            action="BUY",
            order_type="market",
            quantity=-1.0,
            status="pending",
            timestamp=datetime.now(timezone.utc),
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_order_constraint_rejects_conviction_above_100(session):
    session.add(
        Order(
            ticker="AAPL_US_EQ",
            action="BUY",
            order_type="market",
            quantity=1.0,
            conviction=101,
            status="pending",
            timestamp=datetime.now(timezone.utc),
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_strategy_and_risk_constraints_reject_invalid_allocations(session):
    session.add(
        StrategyDecision(
            cycle_id="cycle_1",
            ticker="AAPL_US_EQ",
            action="BUY",
            target_allocation_pct=120.0,
            timestamp=datetime.now(timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()

    session.add(
        RiskDecision(
            cycle_id="cycle_1",
            ticker="AAPL_US_EQ",
            proposed_action="BUY",
            verdict="APPROVE",
            adjusted_allocation_pct=-5.0,
            timestamp=datetime.now(timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_moderation_constraint_rejects_score_outside_range(session):
    session.add(
        ModerationLog(
            cycle_id="cycle_1",
            ticker="AAPL_US_EQ",
            moderator="gpt-4o",
            verdict="AGREE",
            confidence_score=11,
            timestamp=datetime.now(timezone.utc),
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
