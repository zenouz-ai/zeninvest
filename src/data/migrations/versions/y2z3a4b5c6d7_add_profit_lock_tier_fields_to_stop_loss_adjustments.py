"""add profit-lock tier metadata to stop_loss_adjustments

Revision ID: y2z3a4b5c6d7
Revises: x1y2z3a4b5c6
Create Date: 2026-03-30 11:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "y2z3a4b5c6d7"
down_revision: Union[str, None] = "x1y2z3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("stop_loss_adjustments") as batch_op:
        batch_op.add_column(sa.Column("tier_gain_trigger_pct", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("tier_min_lock_pct", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("tier_rule_label", sa.String(length=50), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("stop_loss_adjustments") as batch_op:
        batch_op.drop_column("tier_rule_label")
        batch_op.drop_column("tier_min_lock_pct")
        batch_op.drop_column("tier_gain_trigger_pct")
