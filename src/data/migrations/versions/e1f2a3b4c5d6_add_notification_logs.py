"""add notification logs table

Revision ID: e1f2a3b4c5d6
Revises: c9d3a1e5b7f1
Create Date: 2026-03-04 23:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "c9d3a1e5b7f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notification_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("cycle_id", sa.String(length=50), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("recipient", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dedup_key", sa.String(length=200), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notification_logs_timestamp"), "notification_logs", ["timestamp"], unique=False)
    op.create_index(op.f("ix_notification_logs_event_id"), "notification_logs", ["event_id"], unique=False)
    op.create_index(op.f("ix_notification_logs_cycle_id"), "notification_logs", ["cycle_id"], unique=False)
    op.create_index(op.f("ix_notification_logs_event_type"), "notification_logs", ["event_type"], unique=False)
    op.create_index(op.f("ix_notification_logs_channel"), "notification_logs", ["channel"], unique=False)
    op.create_index(op.f("ix_notification_logs_dedup_key"), "notification_logs", ["dedup_key"], unique=False)
    op.create_index("ix_notification_logs_event_type_timestamp", "notification_logs", ["event_type", "timestamp"], unique=False)
    op.create_index("ix_notification_logs_channel_timestamp", "notification_logs", ["channel", "timestamp"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_notification_logs_channel_timestamp", table_name="notification_logs")
    op.drop_index("ix_notification_logs_event_type_timestamp", table_name="notification_logs")
    op.drop_index(op.f("ix_notification_logs_dedup_key"), table_name="notification_logs")
    op.drop_index(op.f("ix_notification_logs_channel"), table_name="notification_logs")
    op.drop_index(op.f("ix_notification_logs_event_type"), table_name="notification_logs")
    op.drop_index(op.f("ix_notification_logs_cycle_id"), table_name="notification_logs")
    op.drop_index(op.f("ix_notification_logs_event_id"), table_name="notification_logs")
    op.drop_index(op.f("ix_notification_logs_timestamp"), table_name="notification_logs")
    op.drop_table("notification_logs")
