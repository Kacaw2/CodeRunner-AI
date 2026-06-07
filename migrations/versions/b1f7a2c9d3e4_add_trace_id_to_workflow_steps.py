"""add trace_id to workflow_steps

Revision ID: b1f7a2c9d3e4
Revises: e21895a59f7d
Create Date: 2026-06-05 00:00:00.000000

T1 (Phase 4): bind each workflow step to the trace_id of its agent run.
Logical reference to agent_trace_runs.trace_id; no FK to avoid cross-ORM/cross-db
coupling with the plain-SQLAlchemy trace tables.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1f7a2c9d3e4'
down_revision = 'e21895a59f7d'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('workflow_steps', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trace_id', sa.String(length=64), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_workflow_steps_trace_id'), ['trace_id'], unique=False
        )


def downgrade():
    with op.batch_alter_table('workflow_steps', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_workflow_steps_trace_id'))
        batch_op.drop_column('trace_id')
