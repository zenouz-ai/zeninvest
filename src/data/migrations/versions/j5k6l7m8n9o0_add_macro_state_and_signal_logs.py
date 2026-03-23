"""add macro state and signal logs

Revision ID: j5k6l7m8n9o0
Revises: i4j5k6l7m8n9
Create Date: 2026-03-23 13:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "j5k6l7m8n9o0"
down_revision: Union[str, Sequence[str], None] = "i4j5k6l7m8n9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "macro_state",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("regime", sa.String(length=20), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="scheduled_scan"),
        sa.Column("top_signals_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("sector_summary", sa.Text(), nullable=True),
        sa.Column("economic_highlights", sa.Text(), nullable=True),
        sa.Column("raw_payload_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_macro_state_timestamp"), "macro_state", ["timestamp"], unique=False)

    op.create_table(
        "macro_signal_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("state_id", sa.Integer(), nullable=True),
        sa.Column("signal_type", sa.String(length=50), nullable=False),
        sa.Column("signal_text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="scheduled_scan"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("regime", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_macro_signal_logs_timestamp"), "macro_signal_logs", ["timestamp"], unique=False)
    op.create_index(op.f("ix_macro_signal_logs_state_id"), "macro_signal_logs", ["state_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_macro_signal_logs_state_id"), table_name="macro_signal_logs")
    op.drop_index(op.f("ix_macro_signal_logs_timestamp"), table_name="macro_signal_logs")
    op.drop_table("macro_signal_logs")
    op.drop_index(op.f("ix_macro_state_timestamp"), table_name="macro_state")
    op.drop_table("macro_state")
