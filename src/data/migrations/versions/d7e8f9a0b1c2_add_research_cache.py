"""add research_cache table (US-9.4 durable research cache)

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-06-14 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("ticker", sa.String(length=50), nullable=False),
        sa.Column("tool", sa.String(length=50), nullable=False),
        sa.Column("results_json", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_research_cache_cache_key", "research_cache", ["cache_key"], unique=True
    )
    op.create_index(
        "ix_research_cache_expires_at", "research_cache", ["expires_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_research_cache_expires_at", table_name="research_cache")
    op.drop_index("ix_research_cache_cache_key", table_name="research_cache")
    op.drop_table("research_cache")
