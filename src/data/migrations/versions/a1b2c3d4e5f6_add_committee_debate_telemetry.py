"""add committee debate telemetry to moderation_logs

Records, per moderation decision, how many committee rounds ran and whether a
moderator changed its verdict between the opening round and the post-rebuttal
final verdict. This lets offline evaluation segment forward outcomes by
debate participation and verdict churn so the debate's benefit is measurable
over time.

Revision ID: a1b2c3d4e5f6
Revises: f9a0b1c2d3e4
Create Date: 2026-06-21 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("moderation_logs", sa.Column("debate_rounds", sa.Integer(), nullable=True))
    op.add_column("moderation_logs", sa.Column("verdict_changed_in_debate", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("moderation_logs", "verdict_changed_in_debate")
    op.drop_column("moderation_logs", "debate_rounds")
