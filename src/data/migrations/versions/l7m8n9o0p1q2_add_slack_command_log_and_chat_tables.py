"""add slack_command_log, chat_sessions, chat_turns tables

Revision ID: l7m8n9o0p1q2
Revises: k6l7m8n9o0p1
Create Date: 2026-03-23 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "l7m8n9o0p1q2"
down_revision: Union[str, None] = "k6l7m8n9o0p1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "slack_command_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True, index=True),
        sa.Column("channel_id", sa.String(100), nullable=True),
        sa.Column("user_id", sa.String(100), nullable=True),
        sa.Column("thread_ts", sa.String(50), nullable=True),
        sa.Column("raw_message", sa.Text(), nullable=False),
        sa.Column("parsed_intent_json", sa.Text(), nullable=True),
        sa.Column("ticker", sa.String(50), nullable=True, index=True),
        sa.Column("action", sa.String(20), nullable=True),
        sa.Column("cycle_id", sa.String(100), nullable=True, index=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="received"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("response_message", sa.Text(), nullable=True),
    )

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("channel_type", sa.String(20), nullable=False),
        sa.Column("channel_session_key", sa.String(100), nullable=True),
        sa.Column("user_id", sa.String(100), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("context_json", sa.Text(), nullable=True),
        sa.Column("linked_cycle_id", sa.String(100), nullable=True),
    )

    op.create_table(
        "chat_turns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer(), nullable=False, index=True),
        sa.Column("turn_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=True),
        sa.Column("intent_json", sa.Text(), nullable=True),
        sa.Column("resolution_json", sa.Text(), nullable=True),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("chat_turns")
    op.drop_table("chat_sessions")
    op.drop_table("slack_command_log")
