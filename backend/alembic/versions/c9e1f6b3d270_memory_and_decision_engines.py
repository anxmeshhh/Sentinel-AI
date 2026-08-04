"""Memory + Decision engines (Intelligence Core, Phases 6 & 7)

Adds correlated_situations.occurrence_count (the recurrence signal), the
memories table (learned operational knowledge) and the decisions table (grounded
safety-classified proposals). Additive only; no existing table is altered
destructively, so Google/GitHub/Slack are unaffected.

Revision ID: c9e1f6b3d270
Revises: b7d2e4a91c58
Create Date: 2026-08-02 02:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9e1f6b3d270"
down_revision: Union[str, None] = "b7d2e4a91c58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("correlated_situations", sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"))

    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("scope_key", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.Enum("RECURRING_SITUATION", name="memory_kind"), nullable=False),
        sa.Column("subject_key", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("ACTIVE", "FORGOTTEN", name="memory_status"), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("forgotten_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_key", "kind", "subject_key", name="uq_memory_scope_kind_subject"),
    )
    op.create_index(op.f("ix_memories_workspace_id"), "memories", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_memories_scope_key"), "memories", ["scope_key"], unique=False)

    op.create_table(
        "decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("scope_key", sa.String(length=100), nullable=False),
        sa.Column("situation_id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Enum("INFORM", "RECOMMEND", name="decision_kind"), nullable=False),
        sa.Column("action_key", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=500), nullable=False),
        sa.Column("grounded_in", sa.String(length=100), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False),
        sa.Column("memory_informed", sa.Boolean(), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("status", sa.Enum("PROPOSED", "CONFIRMED", "DISMISSED", "EXECUTED", name="decision_status"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["situation_id"], ["correlated_situations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("situation_id", "action_key", name="uq_decision_situation_action"),
    )
    op.create_index(op.f("ix_decisions_workspace_id"), "decisions", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_decisions_scope_key"), "decisions", ["scope_key"], unique=False)
    op.create_index(op.f("ix_decisions_situation_id"), "decisions", ["situation_id"], unique=False)
    op.create_index(op.f("ix_decisions_memory_id"), "decisions", ["memory_id"], unique=False)


def downgrade() -> None:
    op.drop_table("decisions")
    op.drop_table("memories")
    op.drop_column("correlated_situations", "occurrence_count")
