"""Database models and session management for dashboard.

Reuses the existing agent database connection and adds dashboard-specific models.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase

# Import the existing database engine and session factory
from src.data.database import SessionLocal, get_session
from src.data.models import Base as AgentBase


class Base(DeclarativeBase):
    """Base class for dashboard models."""
    pass


class EventsLog(Base):
    """Real-time activity stream for dashboard SSE."""

    __tablename__ = "events_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    event_type = Column(String(50), nullable=False, index=True)  # run_started, run_completed, decision_made, order_placed, etc.
    source = Column(String(50), nullable=False)  # scheduler, screener, strategy, moderation, risk, execution, notifications
    message = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=True)  # Flexible JSON for event-specific data


class Run(Base):
    """Run metadata for dashboard run history.

    Optional lightweight table to simplify run history queries.
    Can also be derived from strategy_decisions.cycle_id + timestamps.
    """

    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cycle_id = Column(String(100), unique=True, nullable=False, index=True)  # e.g. "2026-03-09T08:00:00Z" or "slack-1234567890"
    run_type = Column(String(20), nullable=False)  # scheduled, manual, slack_command
    started_at = Column(DateTime, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="running")  # running, completed, failed
    summary_json = Column(JSON, nullable=True)  # Summary stats: stocks_reviewed, decisions_made, orders_placed, etc.


def init_dashboard_tables():
    """Create dashboard tables in the existing database."""
    # Create all tables (both agent and dashboard) if they don't exist
    AgentBase.metadata.create_all(bind=SessionLocal().bind)
    Base.metadata.create_all(bind=SessionLocal().bind)
