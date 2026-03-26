"""extend slack_command_log for direct and cancel command modes

Revision ID: p1q2r3s4t5u6
Revises: n0p1q2r3s4t
Create Date: 2026-03-26 10:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "p1q2r3s4t5u6"
down_revision: Union[str, None] = "n0p1q2r3s4t"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("slack_command_log") as batch_op:
        batch_op.add_column(sa.Column("command_kind", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("execution_mode", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("target_order_class", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("target_tickers_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("result_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("slack_command_log") as batch_op:
        batch_op.drop_column("result_json")
        batch_op.drop_column("target_tickers_json")
        batch_op.drop_column("target_order_class")
        batch_op.drop_column("execution_mode")
        batch_op.drop_column("command_kind")
