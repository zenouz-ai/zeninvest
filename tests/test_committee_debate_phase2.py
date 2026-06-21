"""Phase 2 committee-debate visibility: stratification slice + live debate-health helper."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data.models import Base, CostLog, ModerationLog, ResearchLog


# --------------------------------------------------------------------------------------
# Offline (lagging) — by_debate_change / by_debate_rounds stratification
# --------------------------------------------------------------------------------------

def test_committee_stratified_includes_debate_slices() -> None:
    from src.learning.evaluation.committee_attribution import compute_committee_stratified

    # 4 rows: changed-verdict rows are mostly bad, unchanged are mostly good.
    df = pd.DataFrame(
        [
            {"label_3class": "big_loser", "ret_30d": -15.0, "verdict_changed_in_debate": 1, "debate_rounds": 2},
            {"label_3class": "big_loser", "ret_30d": -12.0, "verdict_changed_in_debate": 1, "debate_rounds": 2},
            {"label_3class": "big_winner", "ret_30d": 20.0, "verdict_changed_in_debate": 0, "debate_rounds": 2},
            {"label_3class": "big_winner", "ret_30d": 18.0, "verdict_changed_in_debate": 0, "debate_rounds": 1},
        ]
    )
    out = compute_committee_stratified(df)
    assert "by_debate_change" in out and "by_debate_rounds" in out

    by_change = {r["verdict_changed_in_debate"]: r for r in out["by_debate_change"]}
    assert by_change[1]["n"] == 2
    assert by_change[1]["bad_rate"] == pytest.approx(1.0)
    assert by_change[0]["bad_rate"] == pytest.approx(0.0)

    rounds = {r["debate_rounds"]: r for r in out["by_debate_rounds"]}
    assert rounds[2]["n"] == 3 and rounds[1]["n"] == 1


def test_committee_stratified_handles_missing_debate_columns() -> None:
    """Pre-Phase-1 datasets without the debate columns must not break evaluate."""
    from src.learning.evaluation.committee_attribution import compute_committee_stratified

    df = pd.DataFrame([{"label_3class": "big_winner", "ret_30d": 20.0, "moderation_consensus": "APPROVED"}])
    out = compute_committee_stratified(df)
    assert out["by_debate_change"] == []
    assert out["by_debate_rounds"] == []


# --------------------------------------------------------------------------------------
# Live (leading) — compute_debate_health
# --------------------------------------------------------------------------------------

@pytest.fixture
def debate_session(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("src.data.database.get_session", lambda: factory())
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _seed_debate(session) -> None:
    now = datetime.now(timezone.utc)
    # Decision 1: debated; gpt flips, gemini holds; APPROVED.
    session.add_all([
        ModerationLog(timestamp=now, cycle_id="c1", ticker="AAA_US_EQ", moderator="strategy",
                      verdict="AGREE", consensus="APPROVED", debate_rounds=2),
        ModerationLog(timestamp=now, cycle_id="c1", ticker="AAA_US_EQ", moderator="gpt-4o",
                      verdict="AGREE", consensus="APPROVED", debate_rounds=2, verdict_changed_in_debate=True),
        ModerationLog(timestamp=now, cycle_id="c1", ticker="AAA_US_EQ", moderator="gemini-2.5-flash",
                      verdict="AGREE", consensus="APPROVED", debate_rounds=2, verdict_changed_in_debate=False),
        # Decision 2: debated; neither flips; CAUTION.
        ModerationLog(timestamp=now, cycle_id="c2", ticker="BBB_US_EQ", moderator="gpt-4o",
                      verdict="AGREE", consensus="CAUTION", debate_rounds=2, verdict_changed_in_debate=False),
        ModerationLog(timestamp=now, cycle_id="c2", ticker="BBB_US_EQ", moderator="gemini-2.5-flash",
                      verdict="MODIFY", consensus="CAUTION", debate_rounds=2, verdict_changed_in_debate=False),
        # Skeptic research call (proves the tool fix runs) + moderation spend.
        ResearchLog(cycle_id="c1", member="skeptic", ticker="AAA_US_EQ", tool_name="web_search", created_at=now),
        CostLog(timestamp=now, provider="openai", model="gpt-4o", cost_gbp=0.02, purpose="moderation_gpt4o"),
        CostLog(timestamp=now, provider="google", model="gemini", cost_gbp=0.001, purpose="moderation_gemini"),
    ])
    session.commit()


def test_compute_debate_health_aggregates(debate_session) -> None:
    from src.learning.evaluation.committee_attribution import compute_debate_health

    _seed_debate(debate_session)
    out = compute_debate_health(days=30)

    assert out["total_decisions"] == 2
    assert out["debate_participation_rate"] == pytest.approx(1.0)
    # 4 moderator rows carry the flag; only gpt on decision 1 changed -> 1/4.
    assert out["debate_churn_rate"] == pytest.approx(0.25)
    assert out["consensus_mix"] == {"APPROVED": 1, "CAUTION": 1}
    assert out["rounds_distribution"] == {"2": 2}
    assert out["skeptic_tool_calls"] == 1
    assert out["moderation_cost_gbp"] == pytest.approx(0.021)
    assert out["per_moderator_churn"]["gpt-4o"]["churn_rate"] == pytest.approx(0.5)


def test_compute_debate_health_empty(debate_session) -> None:
    from src.learning.evaluation.committee_attribution import compute_debate_health

    out = compute_debate_health(days=30)
    assert out["total_decisions"] == 0
    assert out["debate_churn_rate"] == 0.0
    assert out["consensus_mix"] == {}
    assert out["skeptic_tool_calls"] == 0
