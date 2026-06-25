"""Tests for the atomic cost-budget reserve/settle pipeline (P4-1, US-7.5)."""

import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.data.database import SessionLocal, engine
from src.data.models import Base, CostLog
from src.utils import cost_tracker as ct


@pytest.fixture(autouse=True)
def _setup_db():
    Base.metadata.create_all(engine)
    s = SessionLocal()
    s.query(CostLog).delete()
    s.commit()
    s.close()
    yield
    s = SessionLocal()
    s.query(CostLog).delete()
    s.commit()
    s.close()


def _add_cost(provider: str, cost_gbp: float, state: str | None = None) -> None:
    with SessionLocal() as s:
        s.add(
            CostLog(
                timestamp=datetime.now(timezone.utc),
                provider=provider,
                model="t",
                cost_gbp=cost_gbp,
                reservation_state=state,
            )
        )
        s.commit()


def test_reserve_succeeds_under_budget():
    rid = ct.reserve_budget("anthropic", 0.5, model="claude")
    assert rid is not None
    with SessionLocal() as s:
        row = s.get(CostLog, rid)
        assert row.reservation_state == ct.RESERVATION_PENDING
        assert row.cost_gbp == 0.5


def test_pending_reservation_counts_toward_spend():
    ct.reserve_budget("anthropic", 1.2)
    # exclude_categories mirrors the budget-check read path
    assert ct.get_daily_spend("anthropic", exclude_categories=True) >= 1.2


def test_reserve_denied_when_daily_exceeded():
    _add_cost("anthropic", 2.5)  # anthropic daily limit is 2
    assert ct.reserve_budget("anthropic", 0.1) is None


def test_reserve_denied_when_monthly_exceeded():
    _add_cost("google", 60.0)  # monthly cap is 60
    assert ct.reserve_budget("anthropic", 0.1) is None


def test_settle_updates_actual_cost():
    rid = ct.reserve_budget("anthropic", 1.0)
    ct.settle_reservation(rid, 0.4, input_tokens=100, output_tokens=50, model="claude")
    with SessionLocal() as s:
        row = s.get(CostLog, rid)
        assert row.reservation_state == ct.RESERVATION_SETTLED
        assert row.cost_gbp == 0.4
        assert row.input_tokens == 100


def test_release_removes_pending():
    rid = ct.reserve_budget("anthropic", 1.0)
    ct.release_reservation(rid)
    with SessionLocal() as s:
        assert s.get(CostLog, rid) is None


def test_sweep_removes_only_stale_pending():
    fresh = ct.reserve_budget("anthropic", 0.1)
    stale = ct.reserve_budget("openai", 0.1)
    with SessionLocal() as s:
        s.get(CostLog, stale).timestamp = datetime.now(timezone.utc) - timedelta(minutes=30)
        s.commit()
    removed = ct.sweep_stale_reservations(max_age_minutes=10)
    assert removed == 1
    with SessionLocal() as s:
        assert s.get(CostLog, fresh) is not None
        assert s.get(CostLog, stale) is None


def test_settled_reservations_excluded_from_reporting():
    rid = ct.reserve_budget("anthropic", 1.0)
    # Pending should be hidden from the cost summary, but counted in budget reads.
    summary_pending = ct.get_cost_summary(days=1)
    assert summary_pending.get("anthropic", 0.0) == 0.0
    ct.settle_reservation(rid, 0.7)
    summary_settled = ct.get_cost_summary(days=1)
    assert summary_settled.get("anthropic", 0.0) == pytest.approx(0.7)


def test_budget_guard_legacy_path_logs_cost(monkeypatch):
    monkeypatch.setattr(
        ct,
        "get_settings",
        lambda: SimpleNamespace(
            atomic_budget_enabled=False,
            anthropic_daily_gbp=2.0,
            openai_daily_gbp=1.0,
            google_daily_gbp=1.0,
            total_monthly_gbp=60.0,
            alert_threshold_pct=80.0,
        ),
    )
    with ct.budget_guard("anthropic", 0.5, model="claude", purpose="strategy") as guard:
        assert guard.approved is True
        guard.settle(100, 50)
    with SessionLocal() as s:
        rows = s.query(CostLog).filter_by(provider="anthropic").all()
        assert len(rows) == 1
        assert rows[0].reservation_state is None  # logged, not reserved
        assert rows[0].input_tokens == 100


def test_budget_guard_atomic_path_reserves_and_settles(monkeypatch):
    monkeypatch.setattr(
        ct,
        "get_settings",
        lambda: SimpleNamespace(
            atomic_budget_enabled=True,
            anthropic_daily_gbp=2.0,
            openai_daily_gbp=1.0,
            google_daily_gbp=1.0,
            total_monthly_gbp=60.0,
            alert_threshold_pct=80.0,
        ),
    )
    with ct.budget_guard("anthropic", 0.5, model="claude") as guard:
        assert guard.approved is True
        guard.settle(200, 100)
    with SessionLocal() as s:
        rows = s.query(CostLog).filter_by(provider="anthropic").all()
        assert len(rows) == 1
        assert rows[0].reservation_state == ct.RESERVATION_SETTLED


def test_budget_guard_releases_unsettled_reservation(monkeypatch):
    monkeypatch.setattr(
        ct,
        "get_settings",
        lambda: SimpleNamespace(
            atomic_budget_enabled=True,
            anthropic_daily_gbp=2.0,
            openai_daily_gbp=1.0,
            google_daily_gbp=1.0,
            total_monthly_gbp=60.0,
            alert_threshold_pct=80.0,
        ),
    )
    with ct.budget_guard("anthropic", 0.5) as guard:
        assert guard.approved is True
        # caller skips settle (e.g. early return)
    with SessionLocal() as s:
        assert s.query(CostLog).filter_by(provider="anthropic").count() == 0


def test_concurrent_reservations_cannot_both_exceed_cap():
    """Two threads racing against a near-full cap: exactly one reservation wins."""
    _add_cost("anthropic", 1.5)  # daily limit 2; one more 1.0 reservation tips it over
    results: list[int | None] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        rid = ct.reserve_budget("anthropic", 1.0)
        with lock:
            results.append(rid)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    granted = [r for r in results if r is not None]
    assert len(granted) == 1
