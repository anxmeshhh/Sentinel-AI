"""Microsoft Teams provider + conversation attention types (Sprint 2)

Two enum widenings, both hand-written because autogenerate diffs tables and
columns, not Enum *members*:

1. connections.provider gains MICROSOFT_TEAMS.
2. attention_items.type renames the three SLACK_* members to provider-neutral
   CONVERSATION_* ones, because Slack and Teams now share the same detectors -
   a Teams blocker labelled "slack_blocker" would be plainly wrong in the UI.
   Existing rows are migrated in place (widen -> update -> narrow), so no
   attention item is lost or orphaned.

Note the detectors' dedupe keys are deliberately NOT changed: they are now
namespaced by provider value ("slack_blocker:<ts>"), which is byte-identical to
what Slack already wrote, so no existing row churns or duplicates.

Revision ID: e2c8b4f71a93
Revises: d1a7c93e6b52
Create Date: 2026-08-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e2c8b4f71a93"
down_revision: Union[str, None] = "d1a7c93e6b52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROV_OLD = "'GITHUB','GOOGLE_CALENDAR','GMAIL','GOOGLE_DRIVE','SLACK','MICROSOFT_OUTLOOK_MAIL','MICROSOFT_OUTLOOK_CALENDAR'"
_PROV_NEW = _PROV_OLD + ",'MICROSOFT_TEAMS'"

_AT_BASE = "'IMPORTANT_EMAIL','UPCOMING_MEETING','STALE_PR','FINDING','MANUAL','DEADLINE'"
_AT_OLD = _AT_BASE + ",'SLACK_MENTION','SLACK_BLOCKER','SLACK_URGENT'"
_AT_NEW = _AT_BASE + ",'CONVERSATION_MENTION','CONVERSATION_BLOCKER','CONVERSATION_URGENT'"
_AT_BOTH = _AT_BASE + ",'SLACK_MENTION','SLACK_BLOCKER','SLACK_URGENT','CONVERSATION_MENTION','CONVERSATION_BLOCKER','CONVERSATION_URGENT'"

_RENAMES = (("SLACK_MENTION", "CONVERSATION_MENTION"), ("SLACK_BLOCKER", "CONVERSATION_BLOCKER"), ("SLACK_URGENT", "CONVERSATION_URGENT"))


def upgrade() -> None:
    op.execute(f"ALTER TABLE connections MODIFY provider ENUM({_PROV_NEW}) NOT NULL")

    op.execute(f"ALTER TABLE attention_items MODIFY type ENUM({_AT_BOTH}) NOT NULL")
    for old, new in _RENAMES:
        op.execute(f"UPDATE attention_items SET type = '{new}' WHERE type = '{old}'")
    op.execute(f"ALTER TABLE attention_items MODIFY type ENUM({_AT_NEW}) NOT NULL")


def downgrade() -> None:
    op.execute(f"ALTER TABLE attention_items MODIFY type ENUM({_AT_BOTH}) NOT NULL")
    for old, new in _RENAMES:
        op.execute(f"UPDATE attention_items SET type = '{old}' WHERE type = '{new}'")
    op.execute(f"ALTER TABLE attention_items MODIFY type ENUM({_AT_OLD}) NOT NULL")

    op.execute("DELETE FROM connections WHERE provider = 'MICROSOFT_TEAMS'")
    op.execute(f"ALTER TABLE connections MODIFY provider ENUM({_PROV_OLD}) NOT NULL")
