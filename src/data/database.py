"""Database engine and session management."""

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_DIR = _PROJECT_ROOT / "data"
_DB_DIR.mkdir(exist_ok=True)
_db_override = os.environ.get("INVESTMENT_AGENT_DB_PATH")
_DB_PATH = Path(_db_override) if _db_override else _DB_DIR / "investment_agent.db"

# When running tests (conftest sets this), use in-memory DB so tests never touch production.
if os.environ.get("INVESTMENT_AGENT_USE_INMEMORY_DB") == "1":
    DATABASE_URL = "sqlite:///:memory:"
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    DATABASE_URL = f"sqlite:///{_DB_PATH}"
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
    )


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):  # type: ignore[no-untyped-def]
    """Enable WAL mode and foreign keys for SQLite."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# Process-wide write lock (P4-2, US-7.5 OPS-2 hardening). SQLite allows a single
# writer; this serializes write transactions across threads (scheduled cycle,
# scheduler refresh jobs, dashboard chat) so check-then-write sequences such as
# the atomic cost budget (P4-1) cannot interleave. Reentrant so a holder can
# nest write_transaction() calls. Reads via get_session() are unaffected.
_write_lock = threading.RLock()


def get_write_lock() -> "threading.RLock":
    """Return the process-wide DB write lock (see write_transaction)."""
    return _write_lock


def get_session() -> Session:
    """Create a new database session."""
    return SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a session, commit on success, roll back on error, always close.

    Convenience wrapper around the standard try/commit/except/rollback/finally
    pattern for new code. Does not acquire the write lock — use
    ``write_transaction`` when a write must be serialized against other writers.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def write_transaction() -> Iterator[Session]:
    """Serialized write transaction: hold the write lock for the whole scope.

    Use for read-then-write sequences that must be atomic against concurrent
    writers (e.g. atomic cost-budget check-and-increment). The lock is held
    until the session commits/rolls back and closes.
    """
    with _write_lock:
        with session_scope() as session:
            yield session
