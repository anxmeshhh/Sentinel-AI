"""attention type enum: add UNANSWERED_MAIL

The recency detector (IMPORTANT_EMAIL) only looks back 7 days, which is exactly
backwards for mail that got dropped: the longer it sits, the more invisible it
became. Measured on real data - 27 unread+important messages, only 1 inside the
7-day window - so the backlog was silently unrepresented in the funnel.

Hand written for the usual reason: autogenerate diffs tables and columns, never
Enum members.

Revision ID: a1c7e5b83d92
Revises: f3d6a29c7b41
Create Date: 2026-08-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "a1c7e5b83d92"
down_revision: Union[str, None] = "f3d6a29c7b41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = ("'IMPORTANT_EMAIL','UPCOMING_MEETING','STALE_PR','FINDING','MANUAL','DEADLINE',"
        "'CONVERSATION_MENTION','CONVERSATION_BLOCKER','CONVERSATION_URGENT',"
        "'TASK_OVERDUE','TASK_DUE_TODAY'")
_NEW = _OLD + ",'UNANSWERED_MAIL'"


def upgrade() -> None:
    op.execute(f"ALTER TABLE attention_items MODIFY type ENUM({_NEW}) NOT NULL")


def downgrade() -> None:
    op.execute("DELETE FROM attention_items WHERE type = 'UNANSWERED_MAIL'")
    op.execute(f"ALTER TABLE attention_items MODIFY type ENUM({_OLD}) NOT NULL")
