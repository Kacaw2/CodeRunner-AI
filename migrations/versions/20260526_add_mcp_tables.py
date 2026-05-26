"""Add mcp_api_keys and mcp_audit_logs tables for Phase 3 MCP Server.

Revision ID: add_mcp_tables
Revises: add_workflow_tables
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa


revision = "add_mcp_tables"
down_revision = "add_workflow_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mcp_api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key_hash", sa.String(128), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=True),
        sa.Column("rate_limit_rpm", sa.Integer(), server_default="30"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "mcp_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("api_key_id", sa.String(36),
                  sa.ForeignKey("mcp_api_keys.id"), nullable=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("tool_name", sa.String(50), nullable=False),
        sa.Column("tool_args", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("mcp_audit_logs")
    op.drop_table("mcp_api_keys")
