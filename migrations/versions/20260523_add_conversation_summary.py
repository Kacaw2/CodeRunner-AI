"""Add summary column to ai_conversations for conversation summaries.

Revision ID: add_conversation_summary
Revises: generated_draft_problem_link
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa


revision = "add_conversation_summary"
down_revision = "generated_draft_problem_link"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ai_conversations", sa.Column("summary", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("ai_conversations", "summary")
