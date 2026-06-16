"""Tests for the rejected-ticker proof-of-value spike (scripts/analyze_rejected_tickers.py).

Uses in-memory SQLite (per conftest policy) and an injected deterministic price
fetcher so forward returns -- and therefore the v6 counterfactual labels -- are
fully offline and reproducible.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data.models import Base, OpportunityScoreSnapshot
from src.learning.dataset.labels import LabelComputer
from src.learning.spec import get_default_spec

# Load the script module by path (scripts/ is not an importable package).
_SPEC = importlib.util.spec_from_file_location(
    "analyze_rejected_tickers",
    Path(__file__).resolve().parent.parent / "scripts" / "analyze_rejected_tickers.py",
)
assert _SPEC and _SPEC.loader
analyze = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = analyze  # required so @dataclass introspection resolves the module
_SPEC.loader.exec_module(analyze)


BASE_TS = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
# Forward returns (over the 30d horizon) chosen to land cleanly in each v6 band:
#   >= 7.5% -> big_winner (0.25%/day), (-1.5%, 7.5%) -> stall, <= -1.5% -> big_loser
TARGET_RETURNS = {
    "WINR_US_EQ": 25.0,
    "LOSE_US_EQ": -12.0,
    "STAL_US_EQ": 1.5,
    "GOOD_US_EQ": -10.0,
    "ACCW_US_EQ": 30.0,
}


def _fake_price_fetcher(ticker: str, decision_ts: datetime, max_days: int) -> pd.DataFrame | None:
    """Anchor close at decision_ts; jump to target by day 2 and hold it flat.

    Holding the target flat means every horizon (3/10/30d) resolves to the same
    return, so the v6 band is deterministic regardless of the horizon window.
    """
    target = TARGET_RETURNS.get(ticker)
    if target is None:
        return None
    anchor = 100.0
    future = anchor * (1 + target / 100.0)
    rows = [{"date": decision_ts, "close": anchor, "high": anchor, "low": anchor}]
    for day in (2, max_days):
        rows.append(
            {
                "date": decision_ts + timedelta(days=day),
                "close": future,
                "high": max(anchor, future),
                "low": min(anchor, future),
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()
    yield sess
    sess.close()


def _snap(cycle: str, ticker: str, *, tradable: bool, stage: str) -> OpportunityScoreSnapshot:
    return OpportunityScoreSnapshot(
        timestamp=BASE_TS,
        cycle_id=cycle,
        ticker=ticker,
        action="BUY" if tradable else "HOLD",
        stage=stage,
        is_tradable=tradable,
    )


def _seed(session) -> None:
    session.add_all(
        [
            _snap("c1", "GOOD_US_EQ", tradable=False, stage="risk_reject"),  # correctly avoided loser
            _snap("c1", "LOSE_US_EQ", tradable=False, stage="moderation_blocked"),  # loser
            _snap("c1", "WINR_US_EQ", tradable=False, stage="strategy_hold"),  # false reject (winner)
            _snap("c1", "STAL_US_EQ", tradable=False, stage="opportunity_filtered"),  # stall
            _snap("c1", "ACCW_US_EQ", tradable=True, stage="approved"),  # accepted winner
        ]
    )
    session.commit()


def _run(session):
    spec = get_default_spec()
    computer = LabelComputer(session, spec=spec, price_fetcher=_fake_price_fetcher)
    return analyze.analyze_rejections(session, spec=spec, label_computer=computer)


def test_counterfactual_labels_land_in_expected_bands(session):
    _seed(session)
    spec = get_default_spec()
    computer = LabelComputer(session, spec=spec, price_fetcher=_fake_price_fetcher)
    rejected = analyze.label_rows(
        session, analyze.load_snapshot_rows(session, is_tradable=False), spec=spec, label_computer=computer
    )
    by_ticker = dict(zip(rejected["ticker"], rejected["cf_label"]))
    assert by_ticker["WINR_US_EQ"] == "big_winner"
    assert by_ticker["LOSE_US_EQ"] == "big_loser"
    assert by_ticker["GOOD_US_EQ"] == "big_loser"
    assert by_ticker["STAL_US_EQ"] == "stall"


def test_headline_rates(session):
    _seed(session)
    analysis = _run(session)
    assert analysis.rejected_total == 4
    assert analysis.rejected_resolved == 4
    assert analysis.coverage_pct == 1.0
    # 2 of 4 resolved rejects (GOOD, LOSE) are big_loser -> good-miss 0.5
    assert analysis.good_miss_rate == 0.5
    # 1 of 4 (WINR) is big_winner -> false-reject 0.25
    assert analysis.false_reject_rate == 0.25
    assert analysis.stall_rate == 0.25


def test_selection_gap_positive_when_accepted_outperforms(session):
    _seed(session)
    analysis = _run(session)
    # Accepted name returns +30%; rejected names average well below that.
    assert analysis.accepted_mean_forward_ret_pct is not None
    assert analysis.rejected_mean_forward_ret_pct is not None
    assert analysis.selection_gap_pct is not None
    assert analysis.selection_gap_pct > 0


def test_per_stage_breakdown_flags_false_reject_stage(session):
    _seed(session)
    analysis = _run(session)
    by_stage = {s.stage: s for s in analysis.by_stage}
    # The winner was vetoed at strategy_hold -> that stage shows a false reject.
    assert by_stage["strategy_hold"].false_reject_rate == 1.0
    assert by_stage["risk_reject"].good_miss_rate == 1.0


def test_markdown_renders(session):
    _seed(session)
    md = analyze.render_markdown(_run(session))
    assert "Good-miss rate" in md
    assert "Per-stage veto quality" in md
