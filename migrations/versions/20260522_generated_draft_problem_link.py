"""Add generated draft published problem link.

Revision ID: generated_draft_problem_link
Revises: problem_variant_schema
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa


revision = "generated_draft_problem_link"
down_revision = "problem_variant_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "generated_question_drafts",
        sa.Column("published_problem_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_generated_question_draft_problem",
        "generated_question_drafts",
        "problems",
        ["published_problem_id"],
        ["id"],
    )


def downgrade():
    with op.batch_alter_table("generated_question_drafts") as batch_op:
        batch_op.drop_constraint("fk_generated_question_draft_problem", type_="foreignkey")
        batch_op.drop_column("published_problem_id")
