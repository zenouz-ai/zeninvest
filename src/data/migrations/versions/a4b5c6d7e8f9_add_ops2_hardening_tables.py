"""add OPS-2 hardening schema: cost_logs.reservation_state + halted_instruments (US-7.5)

Revision ID: a4b5c6d7e8f9
Revises: a1b2c3d4e5f6
Create Date: 2026-06-22 00:00:00.000000

Covers P4-1 (atomic cost budget: reservation_state marker on cost_logs) and
P4-4 (time-bounded BUY denial list: halted_instruments table).

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # P4-1: reservation marker for atomic cost-budget reserve/settle.
    op.add_column(
        "cost_logs",
        sa.Column("reservation_state", sa.String(length=20), nullable=True),
    )
    op.create_index(
        "ix_cost_logs_reservation_state",
        "cost_logs",
        ["reservation_state"],
        unique=False,
    )

    # P4-4: time-bounded BUY denial list for broker-rejected instruments.
    op.create_table(
        "halted_instruments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("halted_at", sa.DateTime(), nullable=False),
        sa.Column("halted_until", sa.DateTime(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_halted_instruments_ticker", "halted_instruments", ["ticker"], unique=True
    )
    op.create_index(
        "ix_halted_instruments_halted_until",
        "halted_instruments",
        ["halted_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_halted_instruments_halted_until", table_name="halted_instruments")
    op.drop_index("ix_halted_instruments_ticker", table_name="halted_instruments")
    op.drop_table("halted_instruments")

    op.drop_index("ix_cost_logs_reservation_state", table_name="cost_logs")
    op.drop_column("cost_logs", "reservation_state")
