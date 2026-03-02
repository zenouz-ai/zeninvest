"""add business_summary and industry to instruments

Revision ID: b4c2d5e6f7a8
Revises: a3b1c2d4e5f6
Create Date: 2026-03-02 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4c2d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'a3b1c2d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('instruments', sa.Column('industry', sa.String(150), nullable=True))
    op.add_column('instruments', sa.Column('business_summary', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('instruments', 'business_summary')
    op.drop_column('instruments', 'industry')
