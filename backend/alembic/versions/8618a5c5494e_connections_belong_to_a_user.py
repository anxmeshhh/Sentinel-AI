"""connections belong to a user

Revision ID: 8618a5c5494e
Revises: 208257541c40
Create Date: 2026-07-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '8618a5c5494e'
down_revision: Union[str, None] = '208257541c40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing connections are removed rather than migrated, by explicit
    # decision: every current row predates the notion of an owner, and
    # inventing one would silently attribute an OAuth token to a person who
    # may not have authorized it. Reconnecting is a few clicks and is the
    # only honest way to establish who a token actually belongs to.
    #
    # Signals go with them: a signal is data fetched with a specific
    # token, so orphaning it from its connection would leave mail in the
    # database that nobody can trace back to a grant. Everything re-syncs
    # automatically on reconnect.
    # Strict dependency order - MySQL enforces these foreign keys, so a
    # wrong order fails the whole migration rather than cascading.
    # findings/briefs -> agent_runs -> connections, and
    # channel_connection_resources -> channel_connections -> connections.
    for table in (
        "attention_items",
        "meeting_briefs",
        "email_summaries",
        "findings",
        "briefs",
        "agent_runs",
        "channel_connection_resources",
        "channel_connections",
        "signals",
        "connections",
    ):
        op.execute(f"DELETE FROM {table}")

    op.add_column("connections", sa.Column("user_id", sa.Uuid(), nullable=False))
    op.create_index(op.f("ix_connections_user_id"), "connections", ["user_id"])
    op.create_foreign_key("fk_connections_user_id", "connections", "users", ["user_id"], ["id"])
    op.create_unique_constraint(
        "uq_connection_workspace_user_provider", "connections", ["workspace_id", "user_id", "provider"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_connection_workspace_user_provider", "connections", type_="unique")
    op.drop_constraint("fk_connections_user_id", "connections", type_="foreignkey")
    op.drop_index(op.f("ix_connections_user_id"), table_name="connections")
    op.drop_column("connections", "user_id")
