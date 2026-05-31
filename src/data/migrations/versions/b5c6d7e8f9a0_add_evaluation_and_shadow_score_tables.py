"""add learning_evaluation_runs and decision_shadow_scores tables

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f0
Create Date: 2026-05-30 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, None] = "a4b5c6d7e8f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learning_evaluation_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=100), nullable=False),
        sa.Column("dataset_version", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"),
        sa.Column("n_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closed_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics_json", sa.Text(), nullable=True),
        sa.Column("gates_json", sa.Text(), nullable=True),
        sa.Column("artifact_run_id", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_learning_evaluation_runs_run_id", "learning_evaluation_runs", ["run_id"], unique=True)
    op.create_index(
        "ix_learning_evaluation_runs_dataset_version",
        "learning_evaluation_runs",
        ["dataset_version"],
    )
    op.create_index("ix_learning_evaluation_runs_created_at", "learning_evaluation_runs", ["created_at"])

    op.create_table(
        "decision_shadow_scores",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cycle_id", sa.String(length=100), nullable=False),
        sa.Column("ticker", sa.String(length=50), nullable=False),
        sa.Column("decision_ts", sa.DateTime(), nullable=False),
        sa.Column("champion_action", sa.String(length=30), nullable=False),
        sa.Column("policy_id", sa.String(length=50), nullable=False),
        sa.Column("recommended_action", sa.String(length=30), nullable=False),
        sa.Column("scores_json", sa.Text(), nullable=True),
        sa.Column("artifact_run_ids_json", sa.Text(), nullable=True),
        sa.Column("outcome_json", sa.Text(), nullable=True),
        sa.Column("matured_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decision_shadow_scores_cycle_id", "decision_shadow_scores", ["cycle_id"])
    op.create_index("ix_decision_shadow_scores_ticker", "decision_shadow_scores", ["ticker"])
    op.create_index("ix_decision_shadow_scores_decision_ts", "decision_shadow_scores", ["decision_ts"])
    op.create_index("ix_decision_shadow_scores_policy_id", "decision_shadow_scores", ["policy_id"])
    op.create_index("ix_shadow_scores_cycle_ticker", "decision_shadow_scores", ["cycle_id", "ticker"])
    op.create_index("ix_shadow_scores_policy_ts", "decision_shadow_scores", ["policy_id", "decision_ts"])
    op.create_index("ix_decision_shadow_scores_created_at", "decision_shadow_scores", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_decision_shadow_scores_created_at", table_name="decision_shadow_scores")
    op.drop_index("ix_shadow_scores_policy_ts", table_name="decision_shadow_scores")
    op.drop_index("ix_shadow_scores_cycle_ticker", table_name="decision_shadow_scores")
    op.drop_index("ix_decision_shadow_scores_policy_id", table_name="decision_shadow_scores")
    op.drop_index("ix_decision_shadow_scores_decision_ts", table_name="decision_shadow_scores")
    op.drop_index("ix_decision_shadow_scores_ticker", table_name="decision_shadow_scores")
    op.drop_index("ix_decision_shadow_scores_cycle_id", table_name="decision_shadow_scores")
    op.drop_table("decision_shadow_scores")

    op.drop_index("ix_learning_evaluation_runs_created_at", table_name="learning_evaluation_runs")
    op.drop_index("ix_learning_evaluation_runs_dataset_version", table_name="learning_evaluation_runs")
    op.drop_index("ix_learning_evaluation_runs_run_id", table_name="learning_evaluation_runs")
    op.drop_table("learning_evaluation_runs")
