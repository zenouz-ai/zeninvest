"""add latency_spans table for pipeline timing observability

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-06-17 20:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "latency_spans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("cycle_id", sa.String(length=100), nullable=False),
        sa.Column("run_type", sa.String(length=30), nullable=False),
        sa.Column("job_id", sa.String(length=80), nullable=True),
        sa.Column("span_name", sa.String(length=100), nullable=False),
        sa.Column("parent_span", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_latency_spans_run_id", "latency_spans", ["run_id"], unique=False)
    op.create_index("ix_latency_spans_cycle_id", "latency_spans", ["cycle_id"], unique=False)
    op.create_index("ix_latency_spans_run_type", "latency_spans", ["run_type"], unique=False)
    op.create_index("ix_latency_spans_job_id", "latency_spans", ["job_id"], unique=False)
    op.create_index("ix_latency_spans_span_name", "latency_spans", ["span_name"], unique=False)
    op.create_index("ix_latency_spans_started_at", "latency_spans", ["started_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_latency_spans_started_at", table_name="latency_spans")
    op.drop_index("ix_latency_spans_span_name", table_name="latency_spans")
    op.drop_index("ix_latency_spans_job_id", table_name="latency_spans")
    op.drop_index("ix_latency_spans_run_type", table_name="latency_spans")
    op.drop_index("ix_latency_spans_cycle_id", table_name="latency_spans")
    op.drop_index("ix_latency_spans_run_id", table_name="latency_spans")
    op.drop_table("latency_spans")
