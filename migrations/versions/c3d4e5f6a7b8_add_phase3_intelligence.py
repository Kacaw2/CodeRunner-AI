"""add phase3: student_profiles, teacher_preferences, eval_runs tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-21 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    # Student learning profiles
    op.create_table('student_profiles',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('error_patterns', sa.JSON(), nullable=True),
        sa.Column('knowledge_map', sa.JSON(), nullable=True),
        sa.Column('recent_topics', sa.JSON(), nullable=True),
        sa.Column('recent_questions', sa.JSON(), nullable=True),
        sa.Column('current_hint_level', sa.JSON(), nullable=True),
        sa.Column('learning_summary', sa.Text(), nullable=True),
        sa.Column('preferred_language', sa.String(length=20), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id'),
    )

    # Teacher AI preferences
    op.create_table('teacher_preferences',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('teacher_id', sa.Integer(), nullable=False),
        sa.Column('preferred_difficulty', sa.String(length=20), nullable=True),
        sa.Column('preferred_language', sa.String(length=20), nullable=True),
        sa.Column('preferred_topics', sa.JSON(), nullable=True),
        sa.Column('style_notes', sa.Text(), nullable=True),
        sa.Column('class_weak_areas', sa.JSON(), nullable=True),
        sa.Column('class_level', sa.String(length=20), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['teacher_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('teacher_id'),
    )

    # Eval run tracking
    op.create_table('eval_runs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('suite_name', sa.String(length=50), nullable=False),
        sa.Column('run_at', sa.DateTime(), nullable=True),
        sa.Column('model_name', sa.String(length=50), nullable=True),
        sa.Column('total_cases', sa.Integer(), nullable=True),
        sa.Column('passed_cases', sa.Integer(), nullable=True),
        sa.Column('pass_rate', sa.Float(), nullable=True),
        sa.Column('results_json', sa.JSON(), nullable=True),
        sa.Column('duration_seconds', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('eval_runs')
    op.drop_table('teacher_preferences')
    op.drop_table('student_profiles')
