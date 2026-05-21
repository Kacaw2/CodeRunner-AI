"""add phase2: generated_question_drafts table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-21 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('generated_question_drafts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('task_id', sa.String(length=36), nullable=True),
        sa.Column('conversation_id', sa.Integer(), nullable=True),
        sa.Column('teacher_id', sa.Integer(), nullable=False),
        sa.Column('question_data', sa.JSON(), nullable=False),
        sa.Column('validation_status', sa.String(length=20), nullable=True),
        sa.Column('validation_details', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('revision_count', sa.Integer(), nullable=True),
        sa.Column('published_question_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['agent_tasks.id']),
        sa.ForeignKeyConstraint(['conversation_id'], ['ai_conversations.id']),
        sa.ForeignKeyConstraint(['teacher_id'], ['users.id']),
        sa.ForeignKeyConstraint(['published_question_id'], ['questions.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('generated_question_drafts')
