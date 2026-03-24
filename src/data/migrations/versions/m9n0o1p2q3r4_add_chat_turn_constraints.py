"""add chat_turns integrity constraints

Revision ID: m9n0o1p2q3r4
Revises: b66c726372c9
Create Date: 2026-03-24 15:30:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "m9n0o1p2q3r4"
down_revision: Union[str, None] = "b66c726372c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("chat_turns") as batch_op:
        batch_op.create_foreign_key(
            "fk_chat_turns_session_id_chat_sessions",
            "chat_sessions",
            ["session_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint(
            "uq_chat_turns_session_id_turn_index",
            ["session_id", "turn_index"],
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_turns") as batch_op:
        batch_op.drop_constraint("uq_chat_turns_session_id_turn_index", type_="unique")
        batch_op.drop_constraint("fk_chat_turns_session_id_chat_sessions", type_="foreignkey")
