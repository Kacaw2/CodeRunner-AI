"""Add chat_tasks table for async AI chat processing.

Revision ID: add_chat_tasks
Revises: add_conversation_summary
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa


revision = "add_chat_tasks"
down_revision = "add_conversation_summary"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.Integer(),
                  sa.ForeignKey("ai_conversations.id"), nullable=False),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("user_message_id", sa.Integer(),
                  sa.ForeignKey("ai_messages.id"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="pending"),
        sa.Column("agent_type", sa.String(20), nullable=False,
                  server_default="auto"),
        sa.Column("routed_agent", sa.String(20), nullable=True),
        sa.Column("result_message_id", sa.Integer(),
                  sa.ForeignKey("ai_messages.id"), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_chat_tasks_user_id", "chat_tasks", ["user_id"])
    op.create_index("ix_chat_tasks_status", "chat_tasks", ["status"])
    op.create_index("ix_chat_tasks_conversation_id", "chat_tasks",
                    ["conversation_id"])


def downgrade():
    op.drop_index("ix_chat_tasks_conversation_id")
    op.drop_index("ix_chat_tasks_status")
    op.drop_index("ix_chat_tasks_user_id")
    op.drop_table("chat_tasks")
