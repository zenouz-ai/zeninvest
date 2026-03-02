"""add data_available to instruments

Revision ID: a3b1c2d4e5f6
Revises: 7d4dd410a38f
Create Date: 2026-03-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b1c2d4e5f6'
down_revision: Union[str, Sequence[str], None] = '7d4dd410a38f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('instruments', sa.Column('data_available', sa.Boolean(), server_default='1', nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('instruments', 'data_available')
