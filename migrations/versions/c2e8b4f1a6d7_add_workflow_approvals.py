"""add workflow_approvals

Revision ID: c2e8b4f1a6d7
Revises: b1f7a2c9d3e4
Create Date: 2026-06-05 00:10:00.000000

T2 (Phase 4): immutable audit trail for human-gate decisions on workflow steps
(approver identity, decision, feedback). Replaces stashing feedback inside
WorkflowStep.output_data.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2e8b4f1a6d7'
down_revision = 'b1f7a2c9d3e4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'workflow_approvals',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('workflow_run_id', sa.String(length=36), nullable=False),
        sa.Column('step_index', sa.Integer(), nullable=False),
        sa.Column('approver_user_id', sa.Integer(), nullable=True),
        sa.Column('decision', sa.String(length=20), nullable=False),
        sa.Column('feedback', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['workflow_run_id'], ['workflow_runs.id']),
        sa.ForeignKeyConstraint(['approver_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('workflow_approvals', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_workflow_approvals_workflow_run_id'),
            ['workflow_run_id'], unique=False,
        )


def downgrade():
    with op.batch_alter_table('workflow_approvals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_workflow_approvals_workflow_run_id'))
    op.drop_table('workflow_approvals')
