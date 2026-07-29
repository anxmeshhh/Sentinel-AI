"""attention type enum: add Slack finding types

Phase 3: the deterministic Slack detectors publish findings as attention items,
so the type enum gains slack_mention / slack_blocker / slack_urgent. Hand
written for the usual reason - autogenerate diffs columns, not Enum members.

Revision ID: e7a3c2f19b84
Revises: d9f2b4c81e63
Create Date: 2026-07-29 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e7a3c2f19b84'
down_revision: Union[str, None] = 'd9f2b4c81e63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "'IMPORTANT_EMAIL','UPCOMING_MEETING','STALE_PR','FINDING','MANUAL','DEADLINE'"
_NEW = _OLD + ",'SLACK_MENTION','SLACK_BLOCKER','SLACK_URGENT'"


def upgrade() -> None:
    op.execute(f"ALTER TABLE attention_items MODIFY type ENUM({_NEW}) NOT NULL")


def downgrade() -> None:
    op.execute("DELETE FROM attention_items WHERE type IN ('SLACK_MENTION','SLACK_BLOCKER','SLACK_URGENT')")
    op.execute(f"ALTER TABLE attention_items MODIFY type ENUM({_OLD}) NOT NULL")
