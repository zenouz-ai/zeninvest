"""add guidance and cycle context tables

Revision ID: x1y2z3a4b5c6
Revises: w9x0y1z2a3b4
Create Date: 2026-03-29 13:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "x1y2z3a4b5c6"
down_revision: Union[str, None] = "w9x0y1z2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guidance_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("cycle_id", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("regime", sa.String(length=20), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("freshness_hours", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("prompt_summary", sa.Text(), nullable=True),
        sa.Column("bias_payload_json", sa.Text(), nullable=True),
        sa.Column("evidence_summary_json", sa.Text(), nullable=True),
        sa.Column("raw_payload_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_guidance_snapshots_timestamp"), "guidance_snapshots", ["timestamp"], unique=False)
    op.create_index(op.f("ix_guidance_snapshots_cycle_id"), "guidance_snapshots", ["cycle_id"], unique=False)

    op.create_table(
        "guidance_sector_scores",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guidance_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("sector", sa.String(length=100), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("label", sa.String(length=20), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["guidance_snapshot_id"], ["guidance_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guidance_snapshot_id", "sector", name="uq_guidance_sector_scores_snapshot_sector"),
    )
    op.create_index(op.f("ix_guidance_sector_scores_guidance_snapshot_id"), "guidance_sector_scores", ["guidance_snapshot_id"], unique=False)
    op.create_index(op.f("ix_guidance_sector_scores_sector"), "guidance_sector_scores", ["sector"], unique=False)

    op.create_table(
        "cycle_context_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cycle_id", sa.String(length=50), nullable=False),
        sa.Column("run_type", sa.String(length=20), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("repo_sha", sa.String(length=100), nullable=True),
        sa.Column("config_hash", sa.String(length=64), nullable=True),
        sa.Column("strategy_prompt_hash", sa.String(length=64), nullable=True),
        sa.Column("strategy_fingerprint_hash", sa.String(length=64), nullable=True),
        sa.Column("risk_fingerprint_hash", sa.String(length=64), nullable=True),
        sa.Column("execution_fingerprint_hash", sa.String(length=64), nullable=True),
        sa.Column("guidance_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("guidance_mode", sa.String(length=20), nullable=True),
        sa.Column("prompt_guidance_summary", sa.Text(), nullable=True),
        sa.Column("applied_screening_bias_json", sa.Text(), nullable=True),
        sa.Column("pre_guidance_candidate_count", sa.Integer(), nullable=True),
        sa.Column("post_guidance_candidate_count", sa.Integer(), nullable=True),
        sa.Column("pre_guidance_sector_distribution_json", sa.Text(), nullable=True),
        sa.Column("post_guidance_sector_distribution_json", sa.Text(), nullable=True),
        sa.Column("active_strategy_episode_ids_json", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["guidance_snapshot_id"], ["guidance_snapshots.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cycle_id"),
    )
    op.create_index(op.f("ix_cycle_context_snapshots_cycle_id"), "cycle_context_snapshots", ["cycle_id"], unique=False)
    op.create_index(op.f("ix_cycle_context_snapshots_captured_at"), "cycle_context_snapshots", ["captured_at"], unique=False)
    op.create_index(op.f("ix_cycle_context_snapshots_guidance_snapshot_id"), "cycle_context_snapshots", ["guidance_snapshot_id"], unique=False)
    op.create_index(op.f("ix_cycle_context_snapshots_updated_at"), "cycle_context_snapshots", ["updated_at"], unique=False)

    op.create_table(
        "strategy_change_episodes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("change_type", sa.String(length=30), nullable=False),
        sa.Column("review_confidence", sa.Float(), nullable=True),
        sa.Column("commit_start_sha", sa.String(length=100), nullable=True),
        sa.Column("commit_end_sha", sa.String(length=100), nullable=True),
        sa.Column("effective_start_at", sa.DateTime(), nullable=False),
        sa.Column("effective_end_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategy_change_episodes_status"), "strategy_change_episodes", ["status"], unique=False)
    op.create_index(op.f("ix_strategy_change_episodes_change_type"), "strategy_change_episodes", ["change_type"], unique=False)
    op.create_index(op.f("ix_strategy_change_episodes_effective_start_at"), "strategy_change_episodes", ["effective_start_at"], unique=False)
    op.create_index(op.f("ix_strategy_change_episodes_effective_end_at"), "strategy_change_episodes", ["effective_end_at"], unique=False)
    op.create_index(op.f("ix_strategy_change_episodes_created_at"), "strategy_change_episodes", ["created_at"], unique=False)
    op.create_index(op.f("ix_strategy_change_episodes_updated_at"), "strategy_change_episodes", ["updated_at"], unique=False)

    op.create_table(
        "strategy_change_evidence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("episode_id", sa.Integer(), nullable=False),
        sa.Column("commit_sha", sa.String(length=100), nullable=False),
        sa.Column("committed_at", sa.DateTime(), nullable=False),
        sa.Column("author_name", sa.String(length=200), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("affected_files_json", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["episode_id"], ["strategy_change_episodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategy_change_evidence_episode_id"), "strategy_change_evidence", ["episode_id"], unique=False)
    op.create_index(op.f("ix_strategy_change_evidence_commit_sha"), "strategy_change_evidence", ["commit_sha"], unique=False)
    op.create_index(op.f("ix_strategy_change_evidence_committed_at"), "strategy_change_evidence", ["committed_at"], unique=False)
    op.create_index(op.f("ix_strategy_change_evidence_created_at"), "strategy_change_evidence", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_strategy_change_evidence_created_at"), table_name="strategy_change_evidence")
    op.drop_index(op.f("ix_strategy_change_evidence_committed_at"), table_name="strategy_change_evidence")
    op.drop_index(op.f("ix_strategy_change_evidence_commit_sha"), table_name="strategy_change_evidence")
    op.drop_index(op.f("ix_strategy_change_evidence_episode_id"), table_name="strategy_change_evidence")
    op.drop_table("strategy_change_evidence")

    op.drop_index(op.f("ix_strategy_change_episodes_updated_at"), table_name="strategy_change_episodes")
    op.drop_index(op.f("ix_strategy_change_episodes_created_at"), table_name="strategy_change_episodes")
    op.drop_index(op.f("ix_strategy_change_episodes_effective_end_at"), table_name="strategy_change_episodes")
    op.drop_index(op.f("ix_strategy_change_episodes_effective_start_at"), table_name="strategy_change_episodes")
    op.drop_index(op.f("ix_strategy_change_episodes_change_type"), table_name="strategy_change_episodes")
    op.drop_index(op.f("ix_strategy_change_episodes_status"), table_name="strategy_change_episodes")
    op.drop_table("strategy_change_episodes")

    op.drop_index(op.f("ix_cycle_context_snapshots_updated_at"), table_name="cycle_context_snapshots")
    op.drop_index(op.f("ix_cycle_context_snapshots_guidance_snapshot_id"), table_name="cycle_context_snapshots")
    op.drop_index(op.f("ix_cycle_context_snapshots_captured_at"), table_name="cycle_context_snapshots")
    op.drop_index(op.f("ix_cycle_context_snapshots_cycle_id"), table_name="cycle_context_snapshots")
    op.drop_table("cycle_context_snapshots")

    op.drop_index(op.f("ix_guidance_sector_scores_sector"), table_name="guidance_sector_scores")
    op.drop_index(op.f("ix_guidance_sector_scores_guidance_snapshot_id"), table_name="guidance_sector_scores")
    op.drop_table("guidance_sector_scores")

    op.drop_index(op.f("ix_guidance_snapshots_cycle_id"), table_name="guidance_snapshots")
    op.drop_index(op.f("ix_guidance_snapshots_timestamp"), table_name="guidance_snapshots")
    op.drop_table("guidance_snapshots")
