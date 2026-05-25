"""Add workflow_runs and workflow_steps tables for Supervisor Workflow (Phase 2).

Revision ID: add_workflow_tables
Revises: add_chat_tasks
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa


revision = "add_workflow_tables"
down_revision = "add_chat_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", sa.Integer(),
                  sa.ForeignKey("ai_conversations.id"), nullable=True),
        sa.Column("chat_task_id", sa.String(36),
                  sa.ForeignKey("chat_tasks.id"), nullable=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("workflow_type", sa.String(50), nullable=False,
                  server_default="general"),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="planning"),
        sa.Column("plan_json", sa.JSON(), nullable=True),
        sa.Column("current_step_index", sa.Integer(), server_default="0"),
        sa.Column("total_steps", sa.Integer(), server_default="0"),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("max_steps", sa.Integer(), server_default="10"),
        sa.Column("max_retries_per_step", sa.Integer(), server_default="2"),
        sa.Column("timeout_seconds", sa.Integer(), server_default="300"),
        sa.Column("total_tokens_used", sa.Integer(), server_default="0"),
        sa.Column("total_latency_ms", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_workflow_runs_user_id", "workflow_runs", ["user_id"])
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])
    op.create_index("ix_workflow_runs_chat_task_id", "workflow_runs", ["chat_task_id"])

    op.create_table(
        "workflow_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_run_id", sa.String(36),
                  sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(30), nullable=False),
        sa.Column("agent_type", sa.String(30), nullable=True),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="pending"),
        sa.Column("risk_level", sa.String(10), server_default="low"),
        sa.Column("requires_approval", sa.Boolean(), server_default="0"),
        sa.Column("input_data", sa.JSON(), nullable=True),
        sa.Column("output_data", sa.JSON(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default="0"),
        sa.Column("max_attempts", sa.Integer(), server_default="2"),
        sa.Column("tokens_used", sa.Integer(), server_default="0"),
        sa.Column("latency_ms", sa.Integer(), server_default="0"),
        sa.Column("depends_on", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_workflow_steps_run_id", "workflow_steps", ["workflow_run_id"])
    op.create_index("ix_workflow_steps_status", "workflow_steps", ["status"])


def downgrade():
    op.drop_index("ix_workflow_steps_status")
    op.drop_index("ix_workflow_steps_run_id")
    op.drop_table("workflow_steps")
    op.drop_index("ix_workflow_runs_chat_task_id")
    op.drop_index("ix_workflow_runs_status")
    op.drop_index("ix_workflow_runs_user_id")
    op.drop_table("workflow_runs")
