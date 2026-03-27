"""add chat workflow steps

Revision ID: t6u7v8w9x0y1
Revises: s5t6u7v8w9x0
Create Date: 2026-03-27 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "t6u7v8w9x0y1"
down_revision = "s5t6u7v8w9x0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_workflow_steps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("turn_id", sa.Integer(), nullable=True),
        sa.Column("step_key", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("tool_name", sa.String(length=50), nullable=True),
        sa.Column("cost_gbp", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("detail_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["turn_id"], ["chat_turns.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_workflow_steps_session_id", "chat_workflow_steps", ["session_id"], unique=False)
    op.create_index("ix_chat_workflow_steps_turn_id", "chat_workflow_steps", ["turn_id"], unique=False)
    op.create_index("ix_chat_workflow_steps_step_key", "chat_workflow_steps", ["step_key"], unique=False)
    op.create_index("ix_chat_workflow_steps_status", "chat_workflow_steps", ["status"], unique=False)
    op.create_index("ix_chat_workflow_steps_started_at", "chat_workflow_steps", ["started_at"], unique=False)
    op.create_index("ix_chat_workflow_steps_created_at", "chat_workflow_steps", ["created_at"], unique=False)
    op.create_index("ix_chat_workflow_steps_updated_at", "chat_workflow_steps", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_chat_workflow_steps_updated_at", table_name="chat_workflow_steps")
    op.drop_index("ix_chat_workflow_steps_created_at", table_name="chat_workflow_steps")
    op.drop_index("ix_chat_workflow_steps_started_at", table_name="chat_workflow_steps")
    op.drop_index("ix_chat_workflow_steps_status", table_name="chat_workflow_steps")
    op.drop_index("ix_chat_workflow_steps_step_key", table_name="chat_workflow_steps")
    op.drop_index("ix_chat_workflow_steps_turn_id", table_name="chat_workflow_steps")
    op.drop_index("ix_chat_workflow_steps_session_id", table_name="chat_workflow_steps")
    op.drop_table("chat_workflow_steps")
