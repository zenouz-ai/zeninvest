"""add chat cost attribution to llm and research logs

Revision ID: s5t6u7v8w9x0
Revises: r4s5t6u7v8w9
Create Date: 2026-03-27 13:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "s5t6u7v8w9x0"
down_revision: Union[str, None] = "r4s5t6u7v8w9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cost_logs") as batch_op:
        batch_op.add_column(sa.Column("chat_session_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("chat_turn_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_cost_logs_chat_session_id", ["chat_session_id"], unique=False)
        batch_op.create_index("ix_cost_logs_chat_turn_id", ["chat_turn_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_cost_logs_chat_session_id_chat_sessions",
            "chat_sessions",
            ["chat_session_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_cost_logs_chat_turn_id_chat_turns",
            "chat_turns",
            ["chat_turn_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("research_logs") as batch_op:
        batch_op.add_column(sa.Column("chat_session_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("chat_turn_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_research_logs_chat_session_id", ["chat_session_id"], unique=False)
        batch_op.create_index("ix_research_logs_chat_turn_id", ["chat_turn_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_research_logs_chat_session_id_chat_sessions",
            "chat_sessions",
            ["chat_session_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_research_logs_chat_turn_id_chat_turns",
            "chat_turns",
            ["chat_turn_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("research_logs") as batch_op:
        batch_op.drop_constraint("fk_research_logs_chat_turn_id_chat_turns", type_="foreignkey")
        batch_op.drop_constraint("fk_research_logs_chat_session_id_chat_sessions", type_="foreignkey")
        batch_op.drop_index("ix_research_logs_chat_turn_id")
        batch_op.drop_index("ix_research_logs_chat_session_id")
        batch_op.drop_column("chat_turn_id")
        batch_op.drop_column("chat_session_id")

    with op.batch_alter_table("cost_logs") as batch_op:
        batch_op.drop_constraint("fk_cost_logs_chat_turn_id_chat_turns", type_="foreignkey")
        batch_op.drop_constraint("fk_cost_logs_chat_session_id_chat_sessions", type_="foreignkey")
        batch_op.drop_index("ix_cost_logs_chat_turn_id")
        batch_op.drop_index("ix_cost_logs_chat_session_id")
        batch_op.drop_column("chat_turn_id")
        batch_op.drop_column("chat_session_id")
