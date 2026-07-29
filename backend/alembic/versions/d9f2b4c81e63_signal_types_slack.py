"""signal type enum: add Slack's channel_activity, mention, flagged_message

Phase 2 (Slack ingestion). Hand-written for the usual reason: autogenerate
diffs tables and columns, not Enum *members*, so these exist only in Python
until the DB enum is widened here - without it, inserting a Slack signal fails
with a truncation error at the database.

Revision ID: d9f2b4c81e63
Revises: c5e8a1b40f72
Create Date: 2026-07-29 12:40:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd9f2b4c81e63'
down_revision: Union[str, None] = 'c5e8a1b40f72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "'PR','REVIEW_SUBMITTED','COMMIT','ISSUE','CALENDAR_EVENT','EMAIL','DRIVE_FILE'"
_NEW = _OLD + ",'CHANNEL_ACTIVITY','MENTION','FLAGGED_MESSAGE'"


def upgrade() -> None:
    op.execute(f"ALTER TABLE signals MODIFY type ENUM({_NEW}) NOT NULL")


def downgrade() -> None:
    op.execute("DELETE FROM signals WHERE type IN ('CHANNEL_ACTIVITY','MENTION','FLAGGED_MESSAGE')")
    op.execute(f"ALTER TABLE signals MODIFY type ENUM({_OLD}) NOT NULL")
