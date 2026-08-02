"""entity_mentions: add scope_key (Scope Hardening)

Scope becomes part of the mention's identity so intelligence never crosses the
personal<->channel boundary and a finding shared to several channels can be
mentioned once per scope. Existing mentions are fully derived (re-created every
refresh), so we clear them rather than backfill, then tighten the unique key.

Revision ID: a83f5e1c9d40
Revises: f4b9c1d20a7e
Create Date: 2026-08-02 00:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a83f5e1c9d40"
down_revision: Union[str, None] = "f4b9c1d20a7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Derived data - safe to clear; the next refresh rebuilds it deterministically.
    op.execute("DELETE FROM entity_mentions")
    op.add_column("entity_mentions", sa.Column("scope_key", sa.String(length=100), nullable=False))
    op.create_index(op.f("ix_entity_mentions_scope_key"), "entity_mentions", ["scope_key"], unique=False)
    op.drop_constraint("uq_mention_finding_entity_role", "entity_mentions", type_="unique")
    op.create_unique_constraint(
        "uq_mention_scope_finding_entity_role", "entity_mentions",
        ["scope_key", "finding_id", "entity_id", "role"],
    )


def downgrade() -> None:
    op.execute("DELETE FROM entity_mentions")
    op.drop_constraint("uq_mention_scope_finding_entity_role", "entity_mentions", type_="unique")
    op.create_unique_constraint(
        "uq_mention_finding_entity_role", "entity_mentions",
        ["finding_id", "entity_id", "role"],
    )
    op.drop_index(op.f("ix_entity_mentions_scope_key"), table_name="entity_mentions")
    op.drop_column("entity_mentions", "scope_key")
