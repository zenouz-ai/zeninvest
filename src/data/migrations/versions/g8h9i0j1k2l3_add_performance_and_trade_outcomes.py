"""add performance_metrics and trade_outcomes tables

Revision ID: g8h9i0j1k2l3
Revises: e1f2a3b4c5d6
Create Date: 2026-03-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g8h9i0j1k2l3"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "performance_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("snapshot_date", sa.DateTime(), nullable=False),
        sa.Column("sharpe_30d", sa.Float(), nullable=True),
        sa.Column("sharpe_60d", sa.Float(), nullable=True),
        sa.Column("sharpe_90d", sa.Float(), nullable=True),
        sa.Column("sortino_30d", sa.Float(), nullable=True),
        sa.Column("sortino_60d", sa.Float(), nullable=True),
        sa.Column("sortino_90d", sa.Float(), nullable=True),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=True),
        sa.Column("calmar_ratio", sa.Float(), nullable=True),
        sa.Column("win_rate_momentum", sa.Float(), nullable=True),
        sa.Column("win_rate_mean_reversion", sa.Float(), nullable=True),
        sa.Column("win_rate_factor", sa.Float(), nullable=True),
        sa.Column("alpha_vs_spy_pct", sa.Float(), nullable=True),
        sa.Column("num_trades", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_performance_metrics_snapshot_date"), "performance_metrics", ["snapshot_date"], unique=False)

    op.create_table(
        "trade_outcomes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("buy_order_id", sa.Integer(), nullable=True),
        sa.Column("sell_order_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=50), nullable=False),
        sa.Column("buy_timestamp", sa.DateTime(), nullable=True),
        sa.Column("sell_timestamp", sa.DateTime(), nullable=False),
        sa.Column("holding_days", sa.Float(), nullable=True),
        sa.Column("buy_value_gbp", sa.Float(), nullable=False),
        sa.Column("sell_value_gbp", sa.Float(), nullable=False),
        sa.Column("pnl_gbp", sa.Float(), nullable=False),
        sa.Column("pnl_pct", sa.Float(), nullable=False),
        sa.Column("conviction", sa.Integer(), nullable=True),
        sa.Column("strategy", sa.String(length=50), nullable=True),
        sa.Column("moderation_result", sa.String(length=20), nullable=True),
        sa.Column("risk_result", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trade_outcomes_buy_order_id"), "trade_outcomes", ["buy_order_id"], unique=False)
    op.create_index(op.f("ix_trade_outcomes_sell_order_id"), "trade_outcomes", ["sell_order_id"], unique=True)
    op.create_index(op.f("ix_trade_outcomes_ticker"), "trade_outcomes", ["ticker"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_trade_outcomes_ticker"), table_name="trade_outcomes")
    op.drop_index(op.f("ix_trade_outcomes_sell_order_id"), table_name="trade_outcomes")
    op.drop_index(op.f("ix_trade_outcomes_buy_order_id"), table_name="trade_outcomes")
    op.drop_table("trade_outcomes")
    op.drop_index(op.f("ix_performance_metrics_snapshot_date"), table_name="performance_metrics")
    op.drop_table("performance_metrics")
