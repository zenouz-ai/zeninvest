"""add intent detection cache table

Revision ID: v8w9x0y1z2a3
Revises: u7v8w9x0y1z2
Create Date: 2026-03-28 00:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "v8w9x0y1z2a3"
down_revision = "u7v8w9x0y1z2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "intent_detection_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("normalized_message", sa.Text(), nullable=False),
        sa.Column("example_message", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="claude"),
        sa.Column("intent_kind", sa.String(length=20), nullable=False),
        sa.Column("intent_json", sa.Text(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cache_key"),
    )
    op.create_index("ix_intent_detection_cache_cache_key", "intent_detection_cache", ["cache_key"], unique=True)
    op.create_index("ix_intent_detection_cache_intent_kind", "intent_detection_cache", ["intent_kind"], unique=False)
    op.create_index("ix_intent_detection_cache_created_at", "intent_detection_cache", ["created_at"], unique=False)
    op.create_index("ix_intent_detection_cache_last_used_at", "intent_detection_cache", ["last_used_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_intent_detection_cache_last_used_at", table_name="intent_detection_cache")
    op.drop_index("ix_intent_detection_cache_created_at", table_name="intent_detection_cache")
    op.drop_index("ix_intent_detection_cache_intent_kind", table_name="intent_detection_cache")
    op.drop_index("ix_intent_detection_cache_cache_key", table_name="intent_detection_cache")
    op.drop_table("intent_detection_cache")
