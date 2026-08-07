"""Microsoft Sprint 3: OneDrive, OneNote, To Do

Three enum widenings, hand-written because autogenerate diffs tables and
columns, not Enum members:

  connections.provider    += MICROSOFT_ONEDRIVE / ONENOTE / TODO
  signals.type            += NOTE, TASK  (generic, not Microsoft-specific:
                             a note page and a work item, reusable by Notion
                             or Planner/Jira later)
  attention_items.type    += TASK_OVERDUE, TASK_DUE_TODAY

Additive only - no existing row is touched.

Revision ID: f3d6a29c7b41
Revises: e2c8b4f71a93
Create Date: 2026-08-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f3d6a29c7b41"
down_revision: Union[str, None] = "e2c8b4f71a93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROV_OLD = ("'GITHUB','GOOGLE_CALENDAR','GMAIL','GOOGLE_DRIVE','SLACK',"
             "'MICROSOFT_OUTLOOK_MAIL','MICROSOFT_OUTLOOK_CALENDAR','MICROSOFT_TEAMS'")
_PROV_NEW = _PROV_OLD + ",'MICROSOFT_ONEDRIVE','MICROSOFT_ONENOTE','MICROSOFT_TODO'"

_SIG_OLD = ("'PR','REVIEW_SUBMITTED','COMMIT','ISSUE','CALENDAR_EVENT','EMAIL','DRIVE_FILE',"
            "'CHANNEL_ACTIVITY','MENTION','FLAGGED_MESSAGE'")
_SIG_NEW = _SIG_OLD + ",'NOTE','TASK'"

_AT_OLD = ("'IMPORTANT_EMAIL','UPCOMING_MEETING','STALE_PR','FINDING','MANUAL','DEADLINE',"
           "'CONVERSATION_MENTION','CONVERSATION_BLOCKER','CONVERSATION_URGENT'")
_AT_NEW = _AT_OLD + ",'TASK_OVERDUE','TASK_DUE_TODAY'"


def upgrade() -> None:
    op.execute(f"ALTER TABLE connections MODIFY provider ENUM({_PROV_NEW}) NOT NULL")
    op.execute(f"ALTER TABLE signals MODIFY type ENUM({_SIG_NEW}) NOT NULL")
    op.execute(f"ALTER TABLE attention_items MODIFY type ENUM({_AT_NEW}) NOT NULL")


def downgrade() -> None:
    op.execute("DELETE FROM attention_items WHERE type IN ('TASK_OVERDUE','TASK_DUE_TODAY')")
    op.execute(f"ALTER TABLE attention_items MODIFY type ENUM({_AT_OLD}) NOT NULL")
    op.execute("DELETE FROM signals WHERE type IN ('NOTE','TASK')")
    op.execute(f"ALTER TABLE signals MODIFY type ENUM({_SIG_OLD}) NOT NULL")
    op.execute("DELETE FROM connections WHERE provider IN ('MICROSOFT_ONEDRIVE','MICROSOFT_ONENOTE','MICROSOFT_TODO')")
    op.execute(f"ALTER TABLE connections MODIFY provider ENUM({_PROV_OLD}) NOT NULL")
