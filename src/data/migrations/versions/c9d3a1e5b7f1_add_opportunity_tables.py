"""add opportunity score snapshots and queue tables

Revision ID: c9d3a1e5b7f1
Revises: b4c2d5e6f7a8
Create Date: 2026-03-03 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c9d3a1e5b7f1"
down_revision: Union[str, Sequence[str], None] = "b4c2d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "opportunity_queue",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_cycle_id", sa.String(length=50), nullable=True),
        sa.Column("queued_cycles", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_uov_z", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_uov_final", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_uov_ewma", sa.Float(), nullable=False, server_default="0"),
        sa.Column("action", sa.String(length=10), nullable=False, server_default="BUY"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker"),
    )
    op.create_index(op.f("ix_opportunity_queue_last_seen_cycle_id"), "opportunity_queue", ["last_seen_cycle_id"], unique=False)
    op.create_index(op.f("ix_opportunity_queue_ticker"), "opportunity_queue", ["ticker"], unique=True)

    op.create_table(
        "opportunity_score_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("cycle_id", sa.String(length=50), nullable=False),
        sa.Column("ticker", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=True),
        sa.Column("stage", sa.String(length=50), nullable=True),
        sa.Column("is_tradable", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("uov_raw", sa.Float(), nullable=False, server_default="0"),
        sa.Column("uov_z", sa.Float(), nullable=False, server_default="0"),
        sa.Column("uov_final", sa.Float(), nullable=False, server_default="0"),
        sa.Column("uov_ewma", sa.Float(), nullable=False, server_default="0"),
        sa.Column("previous_uov_ewma", sa.Float(), nullable=True),
        sa.Column("momentum_score", sa.Float(), nullable=True),
        sa.Column("mean_reversion_score", sa.Float(), nullable=True),
        sa.Column("factor_composite_score", sa.Float(), nullable=True),
        sa.Column("factor_quality_score", sa.Float(), nullable=True),
        sa.Column("factor_value_score", sa.Float(), nullable=True),
        sa.Column("conviction", sa.Integer(), nullable=True),
        sa.Column("expected_holding_period", sa.String(length=50), nullable=True),
        sa.Column("gpt_verdict", sa.String(length=20), nullable=True),
        sa.Column("gemini_growth_score", sa.Integer(), nullable=True),
        sa.Column("gemini_risk_score", sa.Integer(), nullable=True),
        sa.Column("gemini_confidence_score", sa.Integer(), nullable=True),
        sa.Column("moderation_consensus", sa.String(length=20), nullable=True),
        sa.Column("risk_verdict", sa.String(length=20), nullable=True),
        sa.Column("news_sentiment_score", sa.Float(), nullable=True),
        sa.Column("market_cap", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_opportunity_score_snapshots_cycle_id"), "opportunity_score_snapshots", ["cycle_id"], unique=False)
    op.create_index(op.f("ix_opportunity_score_snapshots_ticker"), "opportunity_score_snapshots", ["ticker"], unique=False)
    op.create_index(op.f("ix_opportunity_score_snapshots_timestamp"), "opportunity_score_snapshots", ["timestamp"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_opportunity_score_snapshots_timestamp"), table_name="opportunity_score_snapshots")
    op.drop_index(op.f("ix_opportunity_score_snapshots_ticker"), table_name="opportunity_score_snapshots")
    op.drop_index(op.f("ix_opportunity_score_snapshots_cycle_id"), table_name="opportunity_score_snapshots")
    op.drop_table("opportunity_score_snapshots")

    op.drop_index(op.f("ix_opportunity_queue_ticker"), table_name="opportunity_queue")
    op.drop_index(op.f("ix_opportunity_queue_last_seen_cycle_id"), table_name="opportunity_queue")
    op.drop_table("opportunity_queue")
