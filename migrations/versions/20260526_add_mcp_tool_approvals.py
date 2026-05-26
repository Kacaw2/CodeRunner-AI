"""Add mcp_tool_approvals table for Phase 4 Human Gate.

Revision ID: add_mcp_tool_approvals
Revises: add_mcp_tables
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa


revision = "add_mcp_tool_approvals"
down_revision = "add_mcp_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mcp_tool_approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("api_key_id", sa.String(36),
                  sa.ForeignKey("mcp_api_keys.id"), nullable=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("tool_name", sa.String(50), nullable=False),
        sa.Column("tool_args", sa.JSON(), nullable=False),
        sa.Column("risk_level", sa.String(10), server_default="high"),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("reviewer_id", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("mcp_tool_approvals")
