"""add stop_loss_adjustments table

Revision ID: a566f7a38bc7
Revises: g8h9i0j1k2l3
Create Date: 2026-03-06 14:53:48.445116

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a566f7a38bc7'
down_revision: Union[str, Sequence[str], None] = 'g8h9i0j1k2l3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('stop_loss_adjustments',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.Column('cycle_id', sa.String(length=50), nullable=True),
    sa.Column('ticker', sa.String(length=50), nullable=False),
    sa.Column('adjustment_type', sa.String(length=30), nullable=False),
    sa.Column('old_stop_price', sa.Float(), nullable=True),
    sa.Column('new_stop_price', sa.Float(), nullable=True),
    sa.Column('current_price', sa.Float(), nullable=True),
    sa.Column('high_water_mark', sa.Float(), nullable=True),
    sa.Column('atr_value', sa.Float(), nullable=True),
    sa.Column('trigger_reason', sa.String(length=100), nullable=True),
    sa.Column('t212_cancelled_order_id', sa.String(length=100), nullable=True),
    sa.Column('t212_new_order_id', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_stop_loss_adjustments_cycle_id'), 'stop_loss_adjustments', ['cycle_id'], unique=False)
    op.create_index(op.f('ix_stop_loss_adjustments_ticker'), 'stop_loss_adjustments', ['ticker'], unique=False)
    op.create_index(op.f('ix_stop_loss_adjustments_timestamp'), 'stop_loss_adjustments', ['timestamp'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_stop_loss_adjustments_timestamp'), table_name='stop_loss_adjustments')
    op.drop_index(op.f('ix_stop_loss_adjustments_ticker'), table_name='stop_loss_adjustments')
    op.drop_index(op.f('ix_stop_loss_adjustments_cycle_id'), table_name='stop_loss_adjustments')
    op.drop_table('stop_loss_adjustments')
