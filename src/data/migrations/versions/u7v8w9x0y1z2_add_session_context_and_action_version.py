"""add previous_session_id and action version columns

Revision ID: u7v8w9x0y1z2
Revises: t6u7v8w9x0y1
Create Date: 2026-03-28 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "u7v8w9x0y1z2"
down_revision = "t6u7v8w9x0y1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Phase 3: cross-session memory — link sessions to previous session
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("previous_session_id", sa.Integer(), nullable=True)
        )

    # Phase 4: optimistic concurrency on chat actions
    with op.batch_alter_table("chat_actions") as batch_op:
        batch_op.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="1")
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_actions") as batch_op:
        batch_op.drop_column("version")

    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.drop_column("previous_session_id")
