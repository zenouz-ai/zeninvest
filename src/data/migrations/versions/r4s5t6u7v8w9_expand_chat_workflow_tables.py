"""expand chat workflow tables for conversational trading

Revision ID: r4s5t6u7v8w9
Revises: q2r3s4t5u6v7
Create Date: 2026-03-27 12:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "r4s5t6u7v8w9"
down_revision: Union[str, None] = "q2r3s4t5u6v7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.add_column(sa.Column("title", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("last_channel_type", sa.String(length=20), nullable=True))

    with op.batch_alter_table("chat_turns") as batch_op:
        batch_op.add_column(sa.Column("channel_type", sa.String(length=20), nullable=True))

    op.create_table(
        "chat_actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("turn_id", sa.Integer(), nullable=True),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("ticker", sa.String(length=50), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("preview_text", sa.Text(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["turn_id"], ["chat_turns.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_chat_actions_session_id", "chat_actions", ["session_id"])
    op.create_index("ix_chat_actions_turn_id", "chat_actions", ["turn_id"])
    op.create_index("ix_chat_actions_status", "chat_actions", ["status"])
    op.create_index("ix_chat_actions_ticker", "chat_actions", ["ticker"])
    op.create_index("ix_chat_actions_created_at", "chat_actions", ["created_at"])
    op.create_index("ix_chat_actions_updated_at", "chat_actions", ["updated_at"])

    op.create_table(
        "chat_research_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("turn_id", sa.Integer(), nullable=True),
        sa.Column("tool_name", sa.String(length=50), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["turn_id"], ["chat_turns.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_chat_research_logs_session_id", "chat_research_logs", ["session_id"])
    op.create_index("ix_chat_research_logs_turn_id", "chat_research_logs", ["turn_id"])
    op.create_index("ix_chat_research_logs_created_at", "chat_research_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_research_logs_created_at", table_name="chat_research_logs")
    op.drop_index("ix_chat_research_logs_turn_id", table_name="chat_research_logs")
    op.drop_index("ix_chat_research_logs_session_id", table_name="chat_research_logs")
    op.drop_table("chat_research_logs")

    op.drop_index("ix_chat_actions_updated_at", table_name="chat_actions")
    op.drop_index("ix_chat_actions_created_at", table_name="chat_actions")
    op.drop_index("ix_chat_actions_ticker", table_name="chat_actions")
    op.drop_index("ix_chat_actions_status", table_name="chat_actions")
    op.drop_index("ix_chat_actions_turn_id", table_name="chat_actions")
    op.drop_index("ix_chat_actions_session_id", table_name="chat_actions")
    op.drop_table("chat_actions")

    with op.batch_alter_table("chat_turns") as batch_op:
        batch_op.drop_column("channel_type")

    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.drop_column("last_channel_type")
        batch_op.drop_column("title")
