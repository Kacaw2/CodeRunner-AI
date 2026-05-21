"""add phase1 agent tables: agent_tasks, agent_runs, agent_run_steps, ai_audit_logs

Revision ID: a1b2c3d4e5f6
Revises: 81ad73512a67
Create Date: 2026-05-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '81ad73512a67'
branch_labels = None
depends_on = None


def upgrade():
    # agent_tasks
    op.create_table('agent_tasks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=True),
        sa.Column('task_type', sa.String(length=30), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('agent_type', sa.String(length=20), nullable=False),
        sa.Column('input_params', sa.JSON(), nullable=False),
        sa.Column('plan_steps', sa.JSON(), nullable=True),
        sa.Column('current_step', sa.Integer(), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('error_detail', sa.Text(), nullable=True),
        sa.Column('attempt', sa.Integer(), nullable=True),
        sa.Column('max_attempts', sa.Integer(), nullable=True),
        sa.Column('review_status', sa.String(length=20), nullable=True),
        sa.Column('review_feedback', sa.Text(), nullable=True),
        sa.Column('reviewed_by', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['conversation_id'], ['ai_conversations.id']),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # agent_runs
    op.create_table('agent_runs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=True),
        sa.Column('message_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('agent_type', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('input_message', sa.Text(), nullable=True),
        sa.Column('input_context', sa.JSON(), nullable=True),
        sa.Column('output_response', sa.Text(), nullable=True),
        sa.Column('total_latency_ms', sa.Integer(), nullable=True),
        sa.Column('llm_latency_ms', sa.Integer(), nullable=True),
        sa.Column('tool_latency_ms', sa.Integer(), nullable=True),
        sa.Column('tokens_input', sa.Integer(), nullable=True),
        sa.Column('tokens_output', sa.Integer(), nullable=True),
        sa.Column('tool_call_count', sa.Integer(), nullable=True),
        sa.Column('tool_calls_json', sa.JSON(), nullable=True),
        sa.Column('error_type', sa.String(length=50), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('llm_retries', sa.Integer(), nullable=True),
        sa.Column('tool_retries', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['conversation_id'], ['ai_conversations.id']),
        sa.ForeignKeyConstraint(['message_id'], ['ai_messages.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # agent_run_steps
    op.create_table('agent_run_steps',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('step_index', sa.Integer(), nullable=False),
        sa.Column('step_type', sa.String(length=20), nullable=True),
        sa.Column('tool_name', sa.String(length=50), nullable=True),
        sa.Column('tool_input', sa.JSON(), nullable=True),
        sa.Column('tool_output_preview', sa.Text(), nullable=True),
        sa.Column('tool_success', sa.Boolean(), nullable=True),
        sa.Column('llm_prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('llm_completion_tokens', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # ai_audit_logs
    op.create_table('ai_audit_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('agent_type', sa.String(length=20), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=True),
        sa.Column('input_preview', sa.String(length=200), nullable=True),
        sa.Column('injection_detected', sa.Boolean(), nullable=True),
        sa.Column('injection_pattern', sa.String(length=100), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('ai_audit_logs')
    op.drop_table('agent_run_steps')
    op.drop_table('agent_runs')
    op.drop_table('agent_tasks')
