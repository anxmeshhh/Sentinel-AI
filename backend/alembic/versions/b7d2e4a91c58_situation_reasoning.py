"""situation_reasonings (Intelligence Core, Phase 5 - Reasoning Engine)

The reasoning attached to each correlated situation: deterministic priority and
recommended actions (source of truth) plus an optional LLM explanation. Additive
only; no existing table is touched.

Revision ID: b7d2e4a91c58
Revises: a83f5e1c9d40
Create Date: 2026-08-02 01:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d2e4a91c58"
down_revision: Union[str, None] = "a83f5e1c9d40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "situation_reasonings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("situation_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("scope_key", sa.String(length=100), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("headline", sa.String(length=500), nullable=False),
        sa.Column("recommended_actions", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("why_it_matters", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("reasoned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["situation_id"], ["correlated_situations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("situation_id", name="uq_reasoning_situation"),
    )
    op.create_index(op.f("ix_situation_reasonings_situation_id"), "situation_reasonings", ["situation_id"], unique=False)
    op.create_index(op.f("ix_situation_reasonings_workspace_id"), "situation_reasonings", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_situation_reasonings_scope_key"), "situation_reasonings", ["scope_key"], unique=False)


def downgrade() -> None:
    op.drop_table("situation_reasonings")
