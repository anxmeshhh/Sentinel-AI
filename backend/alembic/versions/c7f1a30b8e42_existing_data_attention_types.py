"""attention type enum: the eight existing-data detectors

The detectors that read data Sentinel was already ingesting - overlapping
meetings, a crowded week, slow merges, a review queue, a lone maintainer, a
stale issue, a stalled thread, a cold shared document - each got its own
AttentionType so the Situation Engine can correlate by kind rather than
lumping them into a generic FINDING.

Adding a Python enum member is not adding a database one. `type` is a MySQL
ENUM column, so an INSERT of 'MEETING_CONFLICT' against the old definition
fails with a data-truncation error - and the test suite would not have caught
it, because SQLite does not enforce ENUM membership at all. That gap is the
whole reason this file exists and is hand written: autogenerate diffs tables
and columns, never Enum members.

Revision ID: c7f1a30b8e42
Revises: b4e2f7a91c58
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "c7f1a30b8e42"
down_revision: Union[str, None] = "b4e2f7a91c58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = (
    "'IMPORTANT_EMAIL','UPCOMING_MEETING','STALE_PR','FINDING','MANUAL','DEADLINE',"
    "'CONVERSATION_MENTION','CONVERSATION_BLOCKER','CONVERSATION_URGENT',"
    "'UNANSWERED_MAIL','TASK_OVERDUE','TASK_DUE_TODAY'"
)
_ADDED = (
    "'MEETING_CONFLICT','MEETING_OVERLOAD','PR_SLOW_MERGE','REVIEW_BOTTLENECK',"
    "'BUS_FACTOR','ISSUE_STALE','THREAD_STALL','DOC_STALE'"
)
_NEW = f"{_OLD},{_ADDED}"


def upgrade() -> None:
    op.execute(f"ALTER TABLE attention_items MODIFY type ENUM({_NEW}) NOT NULL")


def downgrade() -> None:
    # Rows of a type the old definition cannot hold are deleted rather than
    # remapped: they are detections, reproduced on the next sync, and guessing
    # which surviving type each one "really" was would corrupt the feed.
    op.execute(
        "DELETE FROM attention_items WHERE type IN ("
        "'MEETING_CONFLICT','MEETING_OVERLOAD','PR_SLOW_MERGE','REVIEW_BOTTLENECK',"
        "'BUS_FACTOR','ISSUE_STALE','THREAD_STALL','DOC_STALE')"
    )
    op.execute(f"ALTER TABLE attention_items MODIFY type ENUM({_OLD}) NOT NULL")
