"""add prompt_hash to strategy_decisions and moderation_logs

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-06-14 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("strategy_decisions", sa.Column("prompt_hash", sa.String(length=64), nullable=True))
    op.add_column("moderation_logs", sa.Column("prompt_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("moderation_logs", "prompt_hash")
    op.drop_column("strategy_decisions", "prompt_hash")
