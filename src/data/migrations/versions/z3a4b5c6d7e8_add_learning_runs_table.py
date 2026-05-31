"""add learning_runs table for trade-outcome learning pipeline (US-2.1 + US-6.1)

Revision ID: z3a4b5c6d7e8
Revises: y2z3a4b5c6d7
Create Date: 2026-05-11 22:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "z3a4b5c6d7e8"
down_revision: Union[str, None] = "y2z3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learning_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=100), nullable=False),
        sa.Column("dataset_version", sa.String(length=20), nullable=False),
        sa.Column("model_kind", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"),
        sa.Column("rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("label_distribution_json", sa.Text(), nullable=True),
        sa.Column("metrics_json", sa.Text(), nullable=True),
        sa.Column("artifact_paths_json", sa.Text(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_learning_runs_run_id", "learning_runs", ["run_id"], unique=True)
    op.create_index("ix_learning_runs_dataset_version", "learning_runs", ["dataset_version"], unique=False)
    op.create_index("ix_learning_runs_created_at", "learning_runs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_learning_runs_created_at", table_name="learning_runs")
    op.drop_index("ix_learning_runs_dataset_version", table_name="learning_runs")
    op.drop_index("ix_learning_runs_run_id", table_name="learning_runs")
    op.drop_table("learning_runs")
