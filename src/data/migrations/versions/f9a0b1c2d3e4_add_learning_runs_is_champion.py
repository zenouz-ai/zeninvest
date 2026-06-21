"""add is_champion flag to learning_runs

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-06-17 22:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("learning_runs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_champion", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.create_index(
        "ix_learning_runs_is_champion",
        "learning_runs",
        ["is_champion"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_learning_runs_is_champion", table_name="learning_runs")
    with op.batch_alter_table("learning_runs", schema=None) as batch_op:
        batch_op.drop_column("is_champion")
