"""add risk parity fields to strategy_decisions

Revision ID: i4j5k6l7m8n9
Revises: 08c0df3b2af8
Create Date: 2026-03-22 19:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "i4j5k6l7m8n9"
down_revision: Union[str, Sequence[str], None] = "08c0df3b2af8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "strategy_decisions",
        sa.Column("risk_parity_target_allocation_pct", sa.Float(), nullable=True),
    )
    op.add_column(
        "strategy_decisions",
        sa.Column("risk_parity_trailing_vol_pct", sa.Float(), nullable=True),
    )
    op.add_column(
        "strategy_decisions",
        sa.Column("risk_parity_applied", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("strategy_decisions", "risk_parity_applied")
    op.drop_column("strategy_decisions", "risk_parity_trailing_vol_pct")
    op.drop_column("strategy_decisions", "risk_parity_target_allocation_pct")
