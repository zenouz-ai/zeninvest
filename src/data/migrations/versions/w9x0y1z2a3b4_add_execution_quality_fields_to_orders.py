"""add execution quality fields to orders

Revision ID: w9x0y1z2a3b4
Revises: v8w9x0y1z2a3
Create Date: 2026-03-29 11:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "w9x0y1z2a3b4"
down_revision: Union[str, None] = "v8w9x0y1z2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(sa.Column("decision_price", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("filled_quantity", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("remaining_quantity", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("slippage_bps", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("resubmitted_from_order_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_orders_resubmitted_from_order_id_orders",
            "orders",
            ["resubmitted_from_order_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_orders_resubmitted_from_order_id",
            ["resubmitted_from_order_id"],
            unique=False,
        )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE orders
            SET
                decision_price = price,
                filled_quantity = 0,
                remaining_quantity = ABS(quantity)
            WHERE order_type = 'market'
              AND status IN ('pending', 'submitting')
              AND t212_order_id IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_index("ix_orders_resubmitted_from_order_id")
        batch_op.drop_constraint("fk_orders_resubmitted_from_order_id_orders", type_="foreignkey")
        batch_op.drop_column("resubmitted_from_order_id")
        batch_op.drop_column("slippage_bps")
        batch_op.drop_column("remaining_quantity")
        batch_op.drop_column("filled_quantity")
        batch_op.drop_column("decision_price")
