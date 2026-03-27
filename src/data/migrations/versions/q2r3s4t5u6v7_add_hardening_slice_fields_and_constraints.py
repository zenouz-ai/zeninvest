"""add hardening slice fields and constraints

Revision ID: q2r3s4t5u6v7
Revises: p1q2r3s4t5u6
Create Date: 2026-03-27 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "q2r3s4t5u6v7"
down_revision: Union[str, None] = "p1q2r3s4t5u6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("system_state") as batch_op:
        batch_op.add_column(sa.Column("halted_recovery_streak", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("peak_inflation_warning_note", sa.Text(), nullable=True))

    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(sa.Column("warning_note", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "ck_orders_quantity_sign_by_action",
            "(action = 'BUY' AND quantity > 0) OR (action IN ('SELL', 'REDUCE') AND quantity < 0)",
        )
        batch_op.create_check_constraint(
            "ck_orders_conviction_range",
            "conviction IS NULL OR (conviction >= 0 AND conviction <= 100)",
        )

    with op.batch_alter_table("strategy_decisions") as batch_op:
        batch_op.create_check_constraint(
            "ck_strategy_decisions_conviction_range",
            "conviction IS NULL OR (conviction >= 0 AND conviction <= 100)",
        )
        batch_op.create_check_constraint(
            "ck_strategy_decisions_target_allocation_range",
            "target_allocation_pct IS NULL OR (target_allocation_pct >= 0 AND target_allocation_pct <= 100)",
        )
        batch_op.create_check_constraint(
            "ck_strategy_decisions_risk_parity_allocation_range",
            "risk_parity_target_allocation_pct IS NULL OR (risk_parity_target_allocation_pct >= 0 AND risk_parity_target_allocation_pct <= 100)",
        )

    with op.batch_alter_table("moderation_logs") as batch_op:
        batch_op.create_check_constraint(
            "ck_moderation_logs_growth_score_range",
            "growth_score IS NULL OR (growth_score >= 1 AND growth_score <= 10)",
        )
        batch_op.create_check_constraint(
            "ck_moderation_logs_risk_score_range",
            "risk_score IS NULL OR (risk_score >= 1 AND risk_score <= 10)",
        )
        batch_op.create_check_constraint(
            "ck_moderation_logs_confidence_score_range",
            "confidence_score IS NULL OR (confidence_score >= 1 AND confidence_score <= 10)",
        )

    with op.batch_alter_table("risk_decisions") as batch_op:
        batch_op.create_check_constraint(
            "ck_risk_decisions_proposed_allocation_range",
            "proposed_allocation_pct IS NULL OR (proposed_allocation_pct >= 0 AND proposed_allocation_pct <= 100)",
        )
        batch_op.create_check_constraint(
            "ck_risk_decisions_adjusted_allocation_range",
            "adjusted_allocation_pct IS NULL OR (adjusted_allocation_pct >= 0 AND adjusted_allocation_pct <= 100)",
        )


def downgrade() -> None:
    with op.batch_alter_table("risk_decisions") as batch_op:
        batch_op.drop_constraint("ck_risk_decisions_adjusted_allocation_range", type_="check")
        batch_op.drop_constraint("ck_risk_decisions_proposed_allocation_range", type_="check")

    with op.batch_alter_table("moderation_logs") as batch_op:
        batch_op.drop_constraint("ck_moderation_logs_confidence_score_range", type_="check")
        batch_op.drop_constraint("ck_moderation_logs_risk_score_range", type_="check")
        batch_op.drop_constraint("ck_moderation_logs_growth_score_range", type_="check")

    with op.batch_alter_table("strategy_decisions") as batch_op:
        batch_op.drop_constraint("ck_strategy_decisions_risk_parity_allocation_range", type_="check")
        batch_op.drop_constraint("ck_strategy_decisions_target_allocation_range", type_="check")
        batch_op.drop_constraint("ck_strategy_decisions_conviction_range", type_="check")

    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_constraint("ck_orders_conviction_range", type_="check")
        batch_op.drop_constraint("ck_orders_quantity_sign_by_action", type_="check")
        batch_op.drop_column("warning_note")

    with op.batch_alter_table("system_state") as batch_op:
        batch_op.drop_column("peak_inflation_warning_note")
        batch_op.drop_column("halted_recovery_streak")

