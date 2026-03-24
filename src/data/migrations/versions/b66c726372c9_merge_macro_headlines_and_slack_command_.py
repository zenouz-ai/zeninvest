"""merge macro_headlines and slack_command_log branches

Revision ID: b66c726372c9
Revises: 3b65184f7a11, l7m8n9o0p1q2
Create Date: 2026-03-24 09:45:27.871523

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b66c726372c9'
down_revision: Union[str, Sequence[str], None] = ('3b65184f7a11', 'l7m8n9o0p1q2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
