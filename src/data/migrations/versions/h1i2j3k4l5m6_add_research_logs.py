"""add research_logs table

Revision ID: h1i2j3k4l5m6
Revises: 45bf123ae39b
Create Date: 2026-03-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h1i2j3k4l5m6"
down_revision: Union[str, Sequence[str], None] = "45bf123ae39b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cycle_id", sa.String(length=50), nullable=True),
        sa.Column("member", sa.String(length=30), nullable=False),
        sa.Column("ticker", sa.String(length=50), nullable=True),
        sa.Column("tool_name", sa.String(length=50), nullable=False),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("num_results", sa.Integer(), nullable=True),
        sa.Column("results_json", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_logs_cycle_id", "research_logs", ["cycle_id"], unique=False)
    op.create_index("ix_research_logs_ticker", "research_logs", ["ticker"], unique=False)
    op.create_index("ix_research_logs_member_ticker", "research_logs", ["member", "ticker"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_research_logs_member_ticker", table_name="research_logs")
    op.drop_index("ix_research_logs_ticker", table_name="research_logs")
    op.drop_index("ix_research_logs_cycle_id", table_name="research_logs")
    op.drop_table("research_logs")
