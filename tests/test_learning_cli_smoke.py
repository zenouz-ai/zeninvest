"""End-to-end CLI smoke test for the learning pipeline.

Builds a tiny synthetic dataset against in-memory SQLite, redirects every
artifact path through the ``INVESTMENT_AGENT_LEARNING_ROOT`` env override,
runs the ``train`` command with ``--skip-gbm --skip-stall`` (calibrator only)
and asserts that a ``learning_runs`` row plus the metrics report land in the
sandbox directory.
"""

from __future__ import annotations

import json
import os
from argparse import Namespace
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

pytest.importorskip("sklearn")


def _seed_in_memory_dataset() -> None:
    from dashboard.backend.app.database import Base as DashboardBase
    from src.data.database import engine, get_session
    from src.data.models import (
        Base,
        Instrument,
        ModerationLog,
        OpportunityScoreSnapshot,
        PortfolioSnapshot,
        RiskDecision,
        StrategyDecision,
    )

    Base.metadata.create_all(bind=engine)
    DashboardBase.metadata.create_all(bind=engine)
    session = get_session()
    try:
        for model in (
            OpportunityScoreSnapshot,
            ModerationLog,
            RiskDecision,
            StrategyDecision,
            PortfolioSnapshot,
            Instrument,
        ):
            session.query(model).delete()
        session.commit()

        session.add(Instrument(ticker="AAPL_US_EQ", name="Apple", sector="Technology"))
        session.flush()
        for i in range(20):
            ts = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc) + timedelta(days=i)
            cycle = f"cycle-smoke-{i:02d}"
            session.add(
                StrategyDecision(
                    cycle_id=cycle,
                    ticker="AAPL_US_EQ",
                    action="BUY",
                    target_allocation_pct=8.0,
                    conviction=50 + (i % 4) * 10,
                    growth_potential="HIGH",
                    risk_level="MEDIUM",
                    primary_strategy="momentum",
                    upside_target_pct=10.0,
                    stop_loss_pct=5.0,
                    expected_holding_period="1 month",
                    timestamp=ts,
                )
            )
            session.add(
                ModerationLog(
                    cycle_id=cycle,
                    ticker="AAPL_US_EQ",
                    moderator="gpt-4o",
                    verdict="AGREE",
                    growth_score=7,
                    risk_score=4,
                    confidence_score=7,
                    timestamp=ts,
                )
            )
            session.add(
                ModerationLog(
                    cycle_id=cycle,
                    ticker="AAPL_US_EQ",
                    moderator="gemini-2.5-flash",
                    verdict="AGREE",
                    growth_score=7,
                    risk_score=4,
                    confidence_score=7,
                    consensus="APPROVED",
                    timestamp=ts,
                )
            )
            session.add(
                RiskDecision(
                    cycle_id=cycle,
                    ticker="AAPL_US_EQ",
                    proposed_action="BUY",
                    proposed_allocation_pct=8.0,
                    verdict="APPROVE",
                    adjusted_allocation_pct=8.0,
                    triggered_rules_json=json.dumps([]),
                    portfolio_state_json=json.dumps({"cash_pct": 35.0, "drawdown_pct": 5.0}),
                    timestamp=ts,
                )
            )
            session.add(
                OpportunityScoreSnapshot(
                    cycle_id=cycle,
                    ticker="AAPL_US_EQ",
                    action="BUY",
                    stage="approved",
                    is_tradable=True,
                    uov_raw=0.4 + 0.01 * i,
                    uov_z=1.0,
                    uov_final=1.0,
                    uov_ewma=0.6 + 0.01 * i,
                    previous_uov_ewma=0.5,
                    momentum_score=70.0,
                    mean_reversion_score=40.0,
                    factor_composite_score=60.0,
                    factor_quality_score=70.0,
                    factor_value_score=50.0,
                    news_sentiment_score=0.05,
                    market_cap=2_000_000_000_000,
                    timestamp=ts,
                )
            )
            session.add(
                PortfolioSnapshot(
                    timestamp=ts - timedelta(minutes=5),
                    total_value_gbp=10_000.0,
                    cash_gbp=4_000.0,
                    invested_gbp=6_000.0,
                    pnl_gbp=200.0,
                    pnl_pct=2.0,
                    num_positions=2,
                    positions_json=json.dumps([]),
                )
            )
        session.commit()
    finally:
        session.close()


def _fake_label_compute(self, decision_rows):
    rows: list[dict] = []
    for idx, row in enumerate(decision_rows):
        ret = 12.0 if idx % 3 == 0 else (-12.0 if idx % 3 == 1 else 1.0)
        if ret >= 10:
            label = "big_winner"
        elif ret <= -10:
            label = "big_loser"
        else:
            label = "neutral"
        rows.append(
            {
                "cycle_id": row["cycle_id"],
                "ticker": row["ticker"],
                "decision_ts": row["timestamp"],
                "realized_pnl_pct": None,
                "realized_holding_days": None,
                "exit_reason": None,
                "actually_traded": False,
                "label_3class": label,
                "ret_3d": ret * 0.2,
                "ret_10d": ret * 0.5,
                "ret_30d": ret,
                "mtm_max_drawdown_3d": -1.0,
                "mtm_max_drawdown_10d": -2.0,
                "mtm_max_drawdown_30d": -3.0,
                "mtm_max_runup_3d": 1.0,
                "mtm_max_runup_10d": 2.0,
                "mtm_max_runup_30d": ret,
            }
        )
    return pd.DataFrame(rows)


def test_cli_smoke_train_persists_learning_run(monkeypatch, tmp_path) -> None:
    _seed_in_memory_dataset()

    sandbox = tmp_path / "repo"
    sandbox.mkdir()
    monkeypatch.setenv("INVESTMENT_AGENT_LEARNING_ROOT", str(sandbox))

    # Avoid hitting yfinance — replace the labeller with a deterministic stub.
    from src.learning.dataset import labels as labels_module

    monkeypatch.setattr(labels_module.LabelComputer, "compute", _fake_label_compute, raising=True)

    from src.learning import cli

    args = Namespace(
        run_id="smoke-20260512",
        skip_gbm=True,
        skip_stall=True,
        seed=42,
    )
    rc = cli._run_train(args)
    assert rc == 0

    merged = sandbox / "data" / "learning" / "parquet" / "v6" / "merged.parquet"
    assert merged.exists(), "merged parquet missing"
    metrics = sandbox / "data" / "learning" / "reports" / "smoke-20260512" / "metrics.json"
    assert metrics.exists(), "metrics.json missing"
    metrics_payload = json.loads(metrics.read_text())
    assert metrics_payload["run_id"] == "smoke-20260512"
    assert metrics_payload["rows"] >= 1

    # Ensure the real data dir was not touched.
    real_smoke = (
        os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    )
    real_path = (
        f"{real_smoke}/investment-agent/data/learning/reports/smoke-20260512"
        if real_smoke.endswith("investment-agent/tests")
        else None
    )
    if real_path:
        assert not os.path.exists(real_path), "smoke artifacts leaked into real data dir"

    # learning_runs row landed in the in-memory DB.
    from src.data.database import get_session
    from src.data.models import LearningRun

    session = get_session()
    try:
        rows = session.query(LearningRun).filter(LearningRun.run_id == "smoke-20260512").all()
    finally:
        session.close()
    assert len(rows) == 1
    assert rows[0].rows >= 1
    label_dist = json.loads(rows[0].label_distribution_json)
    assert sum(label_dist.values()) == rows[0].rows
