"""Unit tests for the learning dataset pipeline.

Covers leakage guards, label derivation, walk-forward split semantics, and a
small end-to-end build with synthetic SQLite rows.

Skips cleanly when the optional ``learning`` poetry extra is not installed
(``pyarrow`` is required for the parquet round-trip in the end-to-end build
test).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

pytest.importorskip("pyarrow")

from src.data.models import (
    Base,
    Instrument,
    MarketDataCache,
    ModerationLog,
    Order,
    OpportunityScoreSnapshot,
    PortfolioSnapshot,
    RiskDecision,
    StrategyDecision,
    TradeOutcome,
)
from src.learning.dataset.builder import DatasetBuilder
from src.learning.dataset.features import FeatureEngineer, _parse_expected_holding_period
from src.learning.dataset.labels import LabelComputer
from src.learning.dataset.splits import WalkForwardSplitter
from src.learning.spec import DatasetSpec, LabelConfig, get_default_spec, label_columns


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def learning_session(tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    # The dataset builder joins the dashboard-owned `runs` table (to exclude
    # dry-run cycles), so create the dashboard schema on the same engine too.
    try:
        from dashboard.backend.app.database import Base as DashboardBase

        DashboardBase.metadata.create_all(engine)
    except ImportError:
        pass
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_minimal_dataset(session) -> None:
    """Seed enough rows for one BUY cycle that produces a labelled outcome."""
    decision_ts = datetime(2026, 3, 10, 14, 0)
    session.add(
        Instrument(
            ticker="AAPL_US_EQ",
            name="Apple Inc.",
            sector="Technology",
            industry="Consumer Electronics",
            market_cap=3_000_000_000_000,
        )
    )
    session.add(
        StrategyDecision(
            cycle_id="cycle-aapl-1",
            ticker="AAPL_US_EQ",
            action="BUY",
            target_allocation_pct=8.0,
            conviction=75,
            growth_potential="HIGH",
            risk_level="MEDIUM",
            primary_strategy="momentum",
            upside_target_pct=18.0,
            stop_loss_pct=8.0,
            expected_holding_period="3 months",
            timestamp=decision_ts,
        )
    )
    session.add(
        ModerationLog(
            cycle_id="cycle-aapl-1",
            ticker="AAPL_US_EQ",
            moderator="gpt-4o",
            verdict="AGREE",
            growth_score=8,
            risk_score=4,
            confidence_score=8,
            timestamp=decision_ts,
            debate_rounds=2,
            verdict_changed_in_debate=True,
        )
    )
    session.add(
        ModerationLog(
            cycle_id="cycle-aapl-1",
            ticker="AAPL_US_EQ",
            moderator="gemini-2.5-flash",
            verdict="AGREE",
            growth_score=8,
            risk_score=5,
            confidence_score=7,
            consensus="APPROVED",
            timestamp=decision_ts,
            debate_rounds=2,
            verdict_changed_in_debate=False,
        )
    )
    session.add(
        RiskDecision(
            cycle_id="cycle-aapl-1",
            ticker="AAPL_US_EQ",
            proposed_action="BUY",
            proposed_allocation_pct=8.0,
            verdict="APPROVE",
            adjusted_allocation_pct=8.0,
            triggered_rules_json=json.dumps([]),
            portfolio_state_json=json.dumps({"cash_pct": 35.0, "drawdown_pct": 5.0}),
            timestamp=decision_ts,
        )
    )
    session.add(
        OpportunityScoreSnapshot(
            cycle_id="cycle-aapl-1",
            ticker="AAPL_US_EQ",
            action="BUY",
            stage="approved",
            is_tradable=True,
            uov_raw=0.42,
            uov_z=1.31,
            uov_final=1.31,
            uov_ewma=0.88,
            previous_uov_ewma=0.74,
            momentum_score=82.0,
            mean_reversion_score=35.0,
            factor_composite_score=76.0,
            factor_quality_score=81.0,
            factor_value_score=58.0,
            news_sentiment_score=0.12,
            market_cap=3_200_000_000_000,
            timestamp=decision_ts,
        )
    )
    session.add(
        MarketDataCache(
            ticker="AAPL_US_EQ",
            data_type="full_analysis",
            timestamp=decision_ts - timedelta(hours=1),
            data_json=json.dumps(
                {
                    "indicators": {
                        "rsi": 56,
                        "macd": 1.2,
                        "atr": 4.5,
                        "volume_ratio_20d": 1.4,
                        "realized_vol_20d": 0.18,
                        "realized_vol_60d": 0.22,
                        "dist_to_50ma": 0.04,
                        "dist_to_200ma": 0.11,
                    },
                    "fundamentals": {
                        "trailing_pe": 25.0,
                        "pb_ratio": 6.2,
                        "roe": 0.28,
                        "profit_margin": 0.23,
                        "debt_equity": 0.5,
                    },
                }
            ),
        )
    )
    session.add(
        PortfolioSnapshot(
            timestamp=decision_ts - timedelta(minutes=10),
            total_value_gbp=10_000.0,
            cash_gbp=4_000.0,
            invested_gbp=6_000.0,
            pnl_gbp=200.0,
            pnl_pct=2.0,
            num_positions=4,
            positions_json=json.dumps(
                [
                    {"ticker": "MSFT_US_EQ", "sector": "Technology", "value_gbp": 1_200.0, "pnl_pct": 5.4},
                    {"ticker": "AAPL_US_EQ", "sector": "Technology", "value_gbp": 800.0, "pnl_pct": 1.2},
                ]
            ),
        )
    )
    session.commit()


# ---------------------------------------------------------------------------
# Spec + labels
# ---------------------------------------------------------------------------


def test_spec_label_columns_includes_horizons() -> None:
    spec = get_default_spec()
    cols = list(label_columns(spec))
    for horizon in spec.labels.horizons_days:
        assert f"ret_{horizon}d" in cols
        assert f"mtm_max_drawdown_{horizon}d" in cols
        assert f"mtm_max_runup_{horizon}d" in cols
    assert "label_3class" in cols
    assert "realized_pnl_pct" in cols


def test_parse_expected_holding_period() -> None:
    assert _parse_expected_holding_period("3 months") == pytest.approx(90.0)
    assert _parse_expected_holding_period("2 weeks") == pytest.approx(14.0)
    assert _parse_expected_holding_period("1-2 years") == pytest.approx(547.5)
    assert _parse_expected_holding_period(None) is None
    assert _parse_expected_holding_period("") is None


def test_label_derivation_big_winner_and_loser(learning_session) -> None:
    spec = DatasetSpec(labels=LabelConfig(horizons_days=(3, 10, 30)))
    computer = LabelComputer(learning_session, spec)
    decision_ts = datetime(2026, 4, 1, 14, 0)

    def fake_prices(ticker: str, _ts: datetime, _days: int) -> pd.DataFrame:
        days = [decision_ts + timedelta(days=i) for i in range(0, 35)]
        closes = [100.0 + i * 0.5 for i in range(0, 35)]
        return pd.DataFrame(
            {"date": days, "close": closes, "high": closes, "low": closes}
        )

    computer._price_fetcher = fake_prices  # type: ignore[attr-defined]
    rows = [{"cycle_id": "c1", "ticker": "AAPL_US_EQ", "timestamp": decision_ts}]
    out = computer.compute(rows)
    assert out.iloc[0]["label_3class"] == "big_winner"

    def fake_prices_loss(ticker: str, _ts: datetime, _days: int) -> pd.DataFrame:
        days = [decision_ts + timedelta(days=i) for i in range(0, 35)]
        closes = [100.0 - i * 0.8 for i in range(0, 35)]
        return pd.DataFrame(
            {"date": days, "close": closes, "high": closes, "low": closes}
        )

    computer._price_fetcher = fake_prices_loss  # type: ignore[attr-defined]
    out2 = computer.compute(rows)
    assert out2.iloc[0]["label_3class"] == "big_loser"


def test_label_stall_when_flat_and_long_held(learning_session) -> None:
    spec = DatasetSpec(labels=LabelConfig(horizons_days=(3, 10, 30), stall_min_holding_days=10))
    computer = LabelComputer(learning_session, spec)
    decision_ts = datetime(2026, 4, 1, 14, 0)

    def fake_prices(ticker: str, _ts: datetime, _days: int) -> pd.DataFrame:
        days = [decision_ts + timedelta(days=i) for i in range(0, 35)]
        # Very flat — within ±1%.
        closes = [100.0 + 0.05 * ((-1) ** i) for i in range(0, 35)]
        return pd.DataFrame({"date": days, "close": closes})

    computer._price_fetcher = fake_prices  # type: ignore[attr-defined]
    rows = [{"cycle_id": "c1", "ticker": "AAPL_US_EQ", "timestamp": decision_ts}]
    out = computer.compute(rows)
    assert out.iloc[0]["label_3class"] == "stall"


# ---------------------------------------------------------------------------
# Feature engineer
# ---------------------------------------------------------------------------


def test_feature_engineer_emits_all_groups(learning_session) -> None:
    _seed_minimal_dataset(learning_session)
    decision_row = {
        "cycle_id": "cycle-aapl-1",
        "ticker": "AAPL_US_EQ",
        "timestamp": datetime(2026, 3, 10, 14, 0),
        "action": "BUY",
        "conviction": 75,
        "target_allocation_pct": 8.0,
        "risk_parity_target_allocation_pct": 6.0,
        "risk_parity_trailing_vol_pct": 0.21,
        "growth_potential": "HIGH",
        "risk_level": "MEDIUM",
        "primary_strategy": "momentum",
        "upside_target_pct": 18.0,
        "stop_loss_pct": 8.0,
        "expected_holding_period": "3 months",
    }
    engineer = FeatureEngineer(learning_session)
    df = engineer.build([decision_row])
    assert len(df) == 1
    row = df.iloc[0]
    # Group A
    assert row["conviction"] == 75
    assert row["target_allocation_pct"] == pytest.approx(8.0)
    assert row["gpt_verdict"] == "AGREE"
    assert row["gemini_verdict"] == "AGREE"
    assert row["moderation_consensus"] == "APPROVED"
    assert row["consensus_disagreement"] == 0
    # Committee-debate telemetry (US-9.13 Phase 2)
    assert int(row["debate_rounds"]) == 2
    assert int(row["verdict_changed_in_debate"]) == 1  # gpt-4o flipped its verdict
    # Group B
    assert row["uov_ewma"] == pytest.approx(0.88)
    assert row["uov_ewma_delta"] == pytest.approx(0.14)
    # Group C
    assert row["rsi_14"] == pytest.approx(56.0)
    assert row["pe_ratio"] == pytest.approx(25.0)
    # Group D
    assert row["cash_pct"] == pytest.approx(40.0)
    assert row["sector_concentration_pct"] == pytest.approx(20.0)
    assert row["existing_position_pct"] == pytest.approx(8.0)
    # Group E (no research rows in fixture)
    assert row["research_calls_total"] == 0


def test_feature_engineer_respects_as_of_ts(learning_session) -> None:
    _seed_minimal_dataset(learning_session)
    # Add a *future* portfolio snapshot — should NOT be used as a feature.
    learning_session.add(
        PortfolioSnapshot(
            timestamp=datetime(2026, 3, 20, 14, 0),
            total_value_gbp=100_000.0,
            cash_gbp=99_000.0,
            invested_gbp=1_000.0,
            pnl_gbp=0.0,
            pnl_pct=0.0,
            num_positions=1,
            positions_json=json.dumps([]),
        )
    )
    learning_session.commit()
    decision_row = {
        "cycle_id": "cycle-aapl-1",
        "ticker": "AAPL_US_EQ",
        "timestamp": datetime(2026, 3, 10, 14, 0),
        "action": "BUY",
        "conviction": 75,
        "target_allocation_pct": 8.0,
        "risk_parity_target_allocation_pct": None,
        "risk_parity_trailing_vol_pct": None,
        "growth_potential": "HIGH",
        "risk_level": "MEDIUM",
        "primary_strategy": "momentum",
        "upside_target_pct": 18.0,
        "stop_loss_pct": 8.0,
        "expected_holding_period": "3 months",
    }
    df = FeatureEngineer(learning_session).build([decision_row])
    # The future £100k snapshot must NOT win the as_of lookup.
    assert df.iloc[0]["portfolio_total_value_gbp"] == pytest.approx(10_000.0)
    assert df.iloc[0]["cash_pct"] == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# Walk-forward splitter
# ---------------------------------------------------------------------------


def test_walk_forward_splits_are_purged_and_embargoed() -> None:
    timestamps = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(120)]
    splitter = WalkForwardSplitter(embargo_days=30, test_window_days=14)
    splits = splitter.split(timestamps)
    assert splits.n_folds >= 1
    for fold in splits.folds:
        # Every train index must be strictly before test_start minus the embargo.
        train_max_ts = max(timestamps[i] for i in fold.train_indices)
        assert (fold.test_start - train_max_ts).days >= splits.embargo_days
        # No overlap between train and test.
        assert set(fold.train_indices).isdisjoint(fold.test_indices)


def test_walk_forward_splits_empty_for_tiny_series() -> None:
    splitter = WalkForwardSplitter(embargo_days=10, test_window_days=14)
    splits = splitter.split([datetime(2026, 1, 1), datetime(2026, 1, 2)])
    assert splits.n_folds == 0


# ---------------------------------------------------------------------------
# End-to-end build (no parquet writes)
# ---------------------------------------------------------------------------


def test_end_to_end_build_no_leakage(learning_session, tmp_path) -> None:
    _seed_minimal_dataset(learning_session)

    decision_ts = datetime(2026, 3, 10, 14, 0)

    def fake_prices(ticker: str, _ts: datetime, _days: int) -> pd.DataFrame:
        days = [decision_ts + timedelta(days=i) for i in range(0, 35)]
        closes = [100.0 + i * 0.4 for i in range(0, 35)]
        return pd.DataFrame(
            {"date": days, "close": closes, "high": closes, "low": closes}
        )

    builder = DatasetBuilder(
        session=learning_session,
        project_root=str(tmp_path),
        price_fetcher=fake_prices,
    )
    result = builder.build(write=True)
    assert result.decisions_rows == 1
    assert result.features_rows == 1
    assert result.labels_rows == 1
    assert result.label_distribution
    # Artifacts should land under tmp_path.
    for path in result.paths.values():
        assert path.startswith(str(tmp_path))
    # Schema file should exist.
    schema_path = tmp_path / "data" / "learning" / "parquet" / "v6" / "schema.json"
    assert schema_path.exists()

    # Leakage assertion: no feature column matches a label column name.
    schema = json.loads(schema_path.read_text())
    feature_cols = set(schema["features_columns"]) - {"cycle_id", "ticker", "decision_ts"}
    label_cols = set(schema["labels_columns"]) - {"cycle_id", "ticker", "decision_ts"}
    assert feature_cols.isdisjoint(label_cols)


def test_build_excludes_dry_run_cycle_decisions(learning_session, tmp_path) -> None:
    from dashboard.backend.app.database import Base as DashboardBase, Run

    DashboardBase.metadata.create_all(learning_session.bind)
    _seed_minimal_dataset(learning_session)
    dry_ts = datetime(2026, 6, 14, 11, 38)
    learning_session.add(
        Run(
            cycle_id="cycle_dry_1",
            run_type="dry_run",
            started_at=dry_ts,
            status="completed",
        )
    )
    learning_session.add(
        StrategyDecision(
            cycle_id="cycle_dry_1",
            ticker="GEF/B_US_EQ",
            action="BUY",
            conviction=80,
            timestamp=dry_ts,
        )
    )
    learning_session.commit()

    def fake_prices(ticker: str, _ts: datetime, _days: int) -> pd.DataFrame:
        days = [dry_ts + timedelta(days=i) for i in range(0, 35)]
        closes = [100.0 + i * 0.2 for i in range(0, 35)]
        return pd.DataFrame({"date": days, "close": closes, "high": closes, "low": closes})

    builder = DatasetBuilder(
        session=learning_session,
        project_root=str(tmp_path),
        price_fetcher=fake_prices,
    )
    result = builder.build(write=False)
    assert result.decisions_rows == 1


def test_build_excludes_refresh_run_type_decisions(learning_session, tmp_path) -> None:
    from dashboard.backend.app.database import Base as DashboardBase, Run

    DashboardBase.metadata.create_all(learning_session.bind)
    _seed_minimal_dataset(learning_session)
    refresh_ts = datetime(2026, 6, 14, 11, 38)
    learning_session.add(
        Run(
            cycle_id="cycle_refresh_1",
            run_type="refresh",
            started_at=refresh_ts,
            status="completed",
        )
    )
    learning_session.add(
        StrategyDecision(
            cycle_id="cycle_refresh_1",
            ticker="GEF/B_US_EQ",
            action="BUY",
            conviction=80,
            timestamp=refresh_ts,
        )
    )
    learning_session.commit()

    def fake_prices(ticker: str, _ts: datetime, _days: int) -> pd.DataFrame:
        days = [refresh_ts + timedelta(days=i) for i in range(0, 35)]
        closes = [100.0 + i * 0.2 for i in range(0, 35)]
        return pd.DataFrame({"date": days, "close": closes, "high": closes, "low": closes})

    builder = DatasetBuilder(
        session=learning_session,
        project_root=str(tmp_path),
        price_fetcher=fake_prices,
    )
    result = builder.build(write=False)
    assert result.decisions_rows == 1
