"""add evolution workflow tables

Revision ID: n0p1q2r3s4t
Revises: m9n0o1p2q3r4
Create Date: 2026-03-25 19:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "n0p1q2r3s4t"
down_revision: Union[str, None] = "m9n0o1p2q3r4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evolution_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source_channel", sa.String(length=20), nullable=False),
        sa.Column("requested_by", sa.String(length=100), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("risk_class", sa.String(length=10), nullable=True),
        sa.Column("latest_plan_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("touched_areas_json", sa.Text(), nullable=True),
        sa.Column("excluded_areas_json", sa.Text(), nullable=True),
        sa.Column("assumptions_json", sa.Text(), nullable=True),
        sa.Column("clarification_questions_json", sa.Text(), nullable=True),
        sa.Column("required_validations_json", sa.Text(), nullable=True),
        sa.Column("current_run_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evolution_requests_status", "evolution_requests", ["status"], unique=False)
    op.create_index("ix_evolution_requests_requested_by", "evolution_requests", ["requested_by"], unique=False)
    op.create_index("ix_evolution_requests_risk_class", "evolution_requests", ["risk_class"], unique=False)
    op.create_index("ix_evolution_requests_created_at", "evolution_requests", ["created_at"], unique=False)
    op.create_index("ix_evolution_requests_updated_at", "evolution_requests", ["updated_at"], unique=False)

    op.create_table(
        "evolution_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("message_type", sa.String(length=30), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["request_id"], ["evolution_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evolution_messages_request_id", "evolution_messages", ["request_id"], unique=False)
    op.create_index("ix_evolution_messages_created_at", "evolution_messages", ["created_at"], unique=False)

    op.create_table(
        "evolution_plans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("change_spec_json", sa.Text(), nullable=False),
        sa.Column("repo_context_json", sa.Text(), nullable=False),
        sa.Column("implementation_steps_json", sa.Text(), nullable=False),
        sa.Column("validation_matrix_json", sa.Text(), nullable=False),
        sa.Column("risk_policy_json", sa.Text(), nullable=False),
        sa.Column("phase_capabilities_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["request_id"], ["evolution_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "version", name="uq_evolution_plans_request_version"),
    )
    op.create_index("ix_evolution_plans_request_id", "evolution_plans", ["request_id"], unique=False)
    op.create_index("ix_evolution_plans_created_at", "evolution_plans", ["created_at"], unique=False)

    op.create_table(
        "evolution_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("run_kind", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.Column("worker_label", sa.String(length=100), nullable=True),
        sa.Column("branch_name", sa.String(length=100), nullable=True),
        sa.Column("commit_sha", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["request_id"], ["evolution_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evolution_runs_request_id", "evolution_runs", ["request_id"], unique=False)
    op.create_index("ix_evolution_runs_started_at", "evolution_runs", ["started_at"], unique=False)

    op.create_table(
        "evolution_artifacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("artifact_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["request_id"], ["evolution_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["evolution_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evolution_artifacts_request_id", "evolution_artifacts", ["request_id"], unique=False)
    op.create_index("ix_evolution_artifacts_run_id", "evolution_artifacts", ["run_id"], unique=False)
    op.create_index("ix_evolution_artifacts_artifact_type", "evolution_artifacts", ["artifact_type"], unique=False)
    op.create_index("ix_evolution_artifacts_created_at", "evolution_artifacts", ["created_at"], unique=False)

    op.create_table(
        "evolution_approvals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("approval_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_by", sa.String(length=100), nullable=True),
        sa.Column("decided_by", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["request_id"], ["evolution_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evolution_approvals_request_id", "evolution_approvals", ["request_id"], unique=False)
    op.create_index("ix_evolution_approvals_created_at", "evolution_approvals", ["created_at"], unique=False)

    op.create_table(
        "evolution_deployments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("approval_id", sa.Integer(), nullable=True),
        sa.Column("environment", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("deploy_ref", sa.String(length=200), nullable=True),
        sa.Column("rollback_ref", sa.String(length=200), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["approval_id"], ["evolution_approvals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["request_id"], ["evolution_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evolution_deployments_request_id", "evolution_deployments", ["request_id"], unique=False)
    op.create_index("ix_evolution_deployments_approval_id", "evolution_deployments", ["approval_id"], unique=False)
    op.create_index("ix_evolution_deployments_created_at", "evolution_deployments", ["created_at"], unique=False)
    op.create_index("ix_evolution_deployments_updated_at", "evolution_deployments", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_evolution_deployments_updated_at", table_name="evolution_deployments")
    op.drop_index("ix_evolution_deployments_created_at", table_name="evolution_deployments")
    op.drop_index("ix_evolution_deployments_approval_id", table_name="evolution_deployments")
    op.drop_index("ix_evolution_deployments_request_id", table_name="evolution_deployments")
    op.drop_table("evolution_deployments")

    op.drop_index("ix_evolution_approvals_created_at", table_name="evolution_approvals")
    op.drop_index("ix_evolution_approvals_request_id", table_name="evolution_approvals")
    op.drop_table("evolution_approvals")

    op.drop_index("ix_evolution_artifacts_created_at", table_name="evolution_artifacts")
    op.drop_index("ix_evolution_artifacts_artifact_type", table_name="evolution_artifacts")
    op.drop_index("ix_evolution_artifacts_run_id", table_name="evolution_artifacts")
    op.drop_index("ix_evolution_artifacts_request_id", table_name="evolution_artifacts")
    op.drop_table("evolution_artifacts")

    op.drop_index("ix_evolution_runs_started_at", table_name="evolution_runs")
    op.drop_index("ix_evolution_runs_request_id", table_name="evolution_runs")
    op.drop_table("evolution_runs")

    op.drop_index("ix_evolution_plans_created_at", table_name="evolution_plans")
    op.drop_index("ix_evolution_plans_request_id", table_name="evolution_plans")
    op.drop_table("evolution_plans")

    op.drop_index("ix_evolution_messages_created_at", table_name="evolution_messages")
    op.drop_index("ix_evolution_messages_request_id", table_name="evolution_messages")
    op.drop_table("evolution_messages")

    op.drop_index("ix_evolution_requests_updated_at", table_name="evolution_requests")
    op.drop_index("ix_evolution_requests_created_at", table_name="evolution_requests")
    op.drop_index("ix_evolution_requests_risk_class", table_name="evolution_requests")
    op.drop_index("ix_evolution_requests_requested_by", table_name="evolution_requests")
    op.drop_index("ix_evolution_requests_status", table_name="evolution_requests")
    op.drop_table("evolution_requests")
