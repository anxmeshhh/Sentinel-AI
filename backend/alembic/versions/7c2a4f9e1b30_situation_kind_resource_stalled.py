"""situation kind repo_stalled -> resource_stalled

Renames the member the classification detector emits. The detector was
generalized from "critical repository gone quiet" to "critical *resource* gone
quiet" (any ingesting provider), so the stored kind follows: a future silent
Slack channel reuses this member instead of copying a new one.

Revision ID: 7c2a4f9e1b30
Revises: 4e31d52a42aa
Create Date: 2026-07-27 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '7c2a4f9e1b30'
down_revision: Union[str, None] = '4e31d52a42aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Hand-written: autogenerate diffs tables and columns, not Enum *members*.
    # Widen the enum to hold both names, migrate any existing rows, then narrow
    # to drop the old name - so no row is ever coerced to '' by the narrowing.
    op.execute(
        "ALTER TABLE situations MODIFY kind "
        "ENUM('SERVICE_JEOPARDY','MEETING_UNPREPARED','REPO_STALLED','RESOURCE_STALLED') NOT NULL"
    )
    op.execute("UPDATE situations SET kind = 'RESOURCE_STALLED' WHERE kind = 'REPO_STALLED'")
    op.execute(
        "ALTER TABLE situations MODIFY kind "
        "ENUM('SERVICE_JEOPARDY','MEETING_UNPREPARED','RESOURCE_STALLED') NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE situations MODIFY kind "
        "ENUM('SERVICE_JEOPARDY','MEETING_UNPREPARED','REPO_STALLED','RESOURCE_STALLED') NOT NULL"
    )
    op.execute("UPDATE situations SET kind = 'REPO_STALLED' WHERE kind = 'RESOURCE_STALLED'")
    op.execute(
        "ALTER TABLE situations MODIFY kind "
        "ENUM('SERVICE_JEOPARDY','MEETING_UNPREPARED','REPO_STALLED') NOT NULL"
    )
