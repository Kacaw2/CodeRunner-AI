"""Add complete trace/eval tables (runtime-neutral source of truth).

Creates the full agent trace tree (run/span/event/artifact/link) plus the
eval case run + grader result tables. These tables are written by workers /
MCP gateway / eval harness through plain SQLAlchemy models on
``core.db.session.Base`` (no Flask-SQLAlchemy mapper), and read by the Flask
service layer. All external object references go through ``agent_trace_links``
rather than hard foreign keys, so the trace store stays decoupled from
business schemas.

Revision ID: complete_traces_evals
Revises: add_mcp_tool_approvals
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa


revision = "complete_traces_evals"
down_revision = "add_mcp_tool_approvals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_trace_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("legacy_run_id", sa.String(36), nullable=True, index=True),
        sa.Column("trace_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("agent_type", sa.String(30), nullable=True, index=True),
        sa.Column("user_id", sa.Integer(), nullable=True, index=True),
        sa.Column("conversation_id", sa.Integer(), nullable=True, index=True),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("chat_task_id", sa.String(36), nullable=True, index=True),
        sa.Column("workflow_run_id", sa.String(36), nullable=True, index=True),
        sa.Column("eval_run_id", sa.Integer(), nullable=True, index=True),
        sa.Column("eval_case_id", sa.String(120), nullable=True, index=True),
        sa.Column("status", sa.String(30), nullable=False, index=True),
        sa.Column("input_preview", sa.Text(), nullable=True),
        sa.Column("output_preview", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(80), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_cny", sa.Numeric(12, 6), nullable=True),
        sa.Column("total_latency_ms", sa.Integer(), nullable=True),
        sa.Column("llm_latency_ms", sa.Integer(), nullable=True),
        sa.Column("tool_latency_ms", sa.Integer(), nullable=True),
        sa.Column("mcp_latency_ms", sa.Integer(), nullable=True),
        sa.Column("sandbox_latency_ms", sa.Integer(), nullable=True),
        sa.Column("budget_json", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "agent_trace_spans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trace_id", sa.String(64), nullable=False, index=True),
        sa.Column("parent_span_id", sa.String(36), nullable=True, index=True),
        sa.Column("span_type", sa.String(40), nullable=False, index=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_preview", sa.Text(), nullable=True),
        sa.Column("output_preview", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=True),
        sa.Column("tokens_output", sa.Integer(), nullable=True),
        sa.Column("cost_cny", sa.Numeric(12, 6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "agent_trace_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trace_id", sa.String(64), nullable=False, index=True),
        sa.Column("span_id", sa.String(36), nullable=True, index=True),
        sa.Column("event_type", sa.String(50), nullable=False, index=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "agent_trace_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trace_id", sa.String(64), nullable=False, index=True),
        sa.Column("span_id", sa.String(36), nullable=True, index=True),
        sa.Column("artifact_type", sa.String(50), nullable=False, index=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("mime_type", sa.String(80), nullable=True),
        sa.Column("storage_uri", sa.String(500), nullable=True),
        sa.Column("preview_text", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "agent_trace_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trace_id", sa.String(64), nullable=False, index=True),
        sa.Column("link_type", sa.String(50), nullable=False, index=True),
        sa.Column("target_table", sa.String(80), nullable=False),
        sa.Column("target_id", sa.String(120), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "eval_case_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("eval_run_id", sa.Integer(), nullable=False, index=True),
        sa.Column("case_id", sa.String(120), nullable=False, index=True),
        sa.Column("case_type", sa.String(30), nullable=True, index=True),
        sa.Column("suite", sa.String(50), nullable=True, index=True),
        sa.Column("agent_type", sa.String(30), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True, index=True),
        sa.Column("status", sa.String(30), nullable=False, index=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("failure_type", sa.String(50), nullable=True, index=True),
        sa.Column("input_preview", sa.Text(), nullable=True),
        sa.Column("output_preview", sa.Text(), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=True),
        sa.Column("tokens_output", sa.Integer(), nullable=True),
        sa.Column("cost_cny", sa.Numeric(12, 6), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "eval_case_grader_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_run_id", sa.String(36), nullable=False, index=True),
        sa.Column("grader_type", sa.String(50), nullable=False, index=True),
        sa.Column("grader_name", sa.String(80), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_cny", sa.Numeric(12, 6), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("eval_case_grader_results")
    op.drop_table("eval_case_runs")
    op.drop_table("agent_trace_links")
    op.drop_table("agent_trace_artifacts")
    op.drop_table("agent_trace_events")
    op.drop_table("agent_trace_spans")
    op.drop_table("agent_trace_runs")
