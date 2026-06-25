"""Tests for DB write serialization helpers (P4-2, US-7.5)."""

import threading

import pytest

from src.data.database import (
    SessionLocal,
    engine,
    get_write_lock,
    session_scope,
    write_transaction,
)
from src.data.models import Base, CostLog


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


def _new_cost_row(value: int = 0) -> int:
    with write_transaction() as s:
        row = CostLog(provider="anthropic", model="t", input_tokens=value, cost_gbp=0.0)
        s.add(row)
        s.flush()
        return int(row.id)


def test_session_scope_commits_on_success():
    rid = _new_cost_row(5)
    with session_scope() as s:
        assert s.get(CostLog, rid).input_tokens == 5


def test_session_scope_rolls_back_on_error():
    rid = _new_cost_row(1)
    with pytest.raises(ValueError):
        with session_scope() as s:
            s.get(CostLog, rid).input_tokens = 999
            raise ValueError("boom")
    with session_scope() as s:
        assert s.get(CostLog, rid).input_tokens == 1


def test_write_transaction_serializes_concurrent_increments():
    """N threads each read-modify-write the same row; the lock prevents lost updates."""
    rid = _new_cost_row(0)
    n_threads = 12
    barrier = threading.Barrier(n_threads)

    def worker() -> None:
        barrier.wait()
        with write_transaction() as s:
            row = s.get(CostLog, rid)
            row.input_tokens = (row.input_tokens or 0) + 1

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with session_scope() as s:
        assert s.get(CostLog, rid).input_tokens == n_threads


def test_write_lock_is_reentrant():
    """write_transaction nests without deadlock (RLock)."""
    lock = get_write_lock()
    with lock:
        with write_transaction() as s:
            s.add(CostLog(provider="openai", model="t", cost_gbp=0.0))
    with session_scope() as s:
        assert s.query(CostLog).filter_by(provider="openai").count() == 1
