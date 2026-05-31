"""add learning_export_runs table for weekly dataset exports

Revision ID: a4b5c6d7e8f0
Revises: z3a4b5c6d7e8
Create Date: 2026-05-29 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4b5c6d7e8f0"
down_revision: Union[str, None] = "z3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learning_export_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=100), nullable=False),
        sa.Column("dataset_version", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"),
        sa.Column("rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text_corpus_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("label_distribution_json", sa.Text(), nullable=True),
        sa.Column("artifact_paths_json", sa.Text(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_learning_export_runs_run_id", "learning_export_runs", ["run_id"], unique=True)
    op.create_index("ix_learning_export_runs_dataset_version", "learning_export_runs", ["dataset_version"])
    op.create_index("ix_learning_export_runs_created_at", "learning_export_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_learning_export_runs_created_at", table_name="learning_export_runs")
    op.drop_index("ix_learning_export_runs_dataset_version", table_name="learning_export_runs")
    op.drop_index("ix_learning_export_runs_run_id", table_name="learning_export_runs")
    op.drop_table("learning_export_runs")
