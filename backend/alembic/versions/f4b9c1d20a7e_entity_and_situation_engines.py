"""Entity Engine + Situation Engine tables (Intelligence Core, Phases 2 & 3)

Creates the Entity Layer (entities, entity_mentions) and the correlated
Situation layer (correlated_situations, situation_findings). Additive only - no
existing table is touched, so Google/GitHub/Slack ingestion and the Finding
consolidation are unaffected.

Enum columns are spelled with the member NAMES (REPO, ABOUT, OPEN, ...) to match
how SQLAlchemy stores Python enums in this project (see the signal_type enum).

Revision ID: f4b9c1d20a7e
Revises: e7a3c2f19b84
Create Date: 2026-08-02 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4b9c1d20a7e"
down_revision: Union[str, None] = "e7a3c2f19b84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Enum("REPO", "CHANNEL", "SERVICE", "PERSON", name="entity_kind"), nullable=False),
        sa.Column("key", sa.String(length=300), nullable=False),
        sa.Column("display_name", sa.String(length=300), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "kind", "key", name="uq_entity_ws_kind_key"),
    )
    op.create_index(op.f("ix_entities_workspace_id"), "entities", ["workspace_id"], unique=False)

    op.create_table(
        "entity_mentions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.String(length=100), nullable=False),
        sa.Column("finding_source", sa.String(length=20), nullable=False),
        sa.Column("role", sa.Enum("ABOUT", "ACTOR", "MENTIONS", name="mention_role"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("finding_id", "entity_id", "role", name="uq_mention_finding_entity_role"),
    )
    op.create_index(op.f("ix_entity_mentions_workspace_id"), "entity_mentions", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_entity_mentions_entity_id"), "entity_mentions", ["entity_id"], unique=False)
    op.create_index(op.f("ix_entity_mentions_finding_id"), "entity_mentions", ["finding_id"], unique=False)

    op.create_table(
        "correlated_situations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("scope_key", sa.String(length=100), nullable=False),
        sa.Column("dedupe_key", sa.String(length=300), nullable=False),
        sa.Column("primary_entity_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Enum("OPEN", "RESOLVED", name="correlated_situation_status"), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("peak_member_count", sa.Integer(), nullable=False),
        sa.Column("provider_count", sa.Integer(), nullable=False),
        sa.Column("cross_provider", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["primary_entity_id"], ["entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_correlated_situation_dedupe"),
    )
    op.create_index(op.f("ix_correlated_situations_workspace_id"), "correlated_situations", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_correlated_situations_scope_key"), "correlated_situations", ["scope_key"], unique=False)
    op.create_index(op.f("ix_correlated_situations_primary_entity_id"), "correlated_situations", ["primary_entity_id"], unique=False)

    op.create_table(
        "situation_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("situation_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.String(length=100), nullable=False),
        sa.Column("finding_source", sa.String(length=20), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["situation_id"], ["correlated_situations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("situation_id", "finding_id", name="uq_situation_finding"),
    )
    op.create_index(op.f("ix_situation_findings_situation_id"), "situation_findings", ["situation_id"], unique=False)
    op.create_index(op.f("ix_situation_findings_finding_id"), "situation_findings", ["finding_id"], unique=False)


def downgrade() -> None:
    op.drop_table("situation_findings")
    op.drop_table("correlated_situations")
    op.drop_table("entity_mentions")
    op.drop_table("entities")
