"""drop legacy quiz_questions table

Revision ID: d9a1f2c3b4e5
Revises: c2e8b4f1a6d7
Create Date: 2026-06-08 01:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d9a1f2c3b4e5"
down_revision = "c2e8b4f1a6d7"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(table_name)


def upgrade():
    if _table_exists("quiz_questions"):
        op.drop_table("quiz_questions")


def downgrade():
    if not _table_exists("quiz_questions"):
        op.create_table(
            "quiz_questions",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("quiz_id", sa.Integer(), nullable=False),
            sa.Column("question_id", sa.Integer(), nullable=False),
            sa.Column("order", sa.Integer(), nullable=False),
            sa.Column("points", sa.Integer(), nullable=True),
            sa.Column("added_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"]),
            sa.ForeignKeyConstraint(["question_id"], ["questions.id"]),
            sa.UniqueConstraint(
                "quiz_id", "question_id", name="unique_quiz_question"
            ),
        )
