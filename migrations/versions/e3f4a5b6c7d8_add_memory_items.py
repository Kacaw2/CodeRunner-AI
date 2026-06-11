"""add memory_items

Revision ID: e3f4a5b6c7d8
Revises: d9a1f2c3b4e5
Create Date: 2026-06-08 00:00:00.000000

Phase 4: governed long-term memory. ``memory_items`` is the item-level
candidate/active/superseded/suppressed/expired governance object that becomes
the source of prompt-injected memory; legacy profile/preference tables remain
only as compatibility materialized views.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e3f4a5b6c7d8'
down_revision = 'd9a1f2c3b4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "memory_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject_type", sa.String(length=30), nullable=False),
        sa.Column("subject_id", sa.String(length=80), nullable=False),
        sa.Column("memory_kind", sa.String(length=40), nullable=False),
        sa.Column("memory_key", sa.String(length=120), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("value_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("sensitivity", sa.String(length=30), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=True),
        sa.Column("source_json", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("superseded_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("memory_items", schema=None) as batch_op:
        batch_op.create_index(
            "ix_memory_subject_status",
            ["subject_type", "subject_id", "status"],
            unique=False,
        )
        batch_op.create_index(
            "ix_memory_key_status",
            ["memory_kind", "memory_key", "status"],
            unique=False,
        )
        batch_op.create_index(
            "ix_memory_value_hash", ["value_hash"], unique=False
        )


def downgrade():
    with op.batch_alter_table("memory_items", schema=None) as batch_op:
        batch_op.drop_index("ix_memory_value_hash")
        batch_op.drop_index("ix_memory_key_status")
        batch_op.drop_index("ix_memory_subject_status")
    op.drop_table("memory_items")
