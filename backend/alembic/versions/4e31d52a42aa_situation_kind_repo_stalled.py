"""situation kind repo_stalled

Revision ID: 4e31d52a42aa
Revises: 297ed57ad033
Create Date: 2026-07-27 17:02:20.424750

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4e31d52a42aa'
down_revision: Union[str, None] = '297ed57ad033'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Hand-written: autogenerate diffs tables and columns, not Enum *members*,
    # so a new SituationKind exists only in Python until the DB enum is widened
    # here - without this, inserting a REPO_STALLED situation fails at the
    # database with a truncation error. Same footgun as the earlier scope and
    # commitment enums.
    op.execute(
        "ALTER TABLE situations MODIFY kind "
        "ENUM('SERVICE_JEOPARDY','MEETING_UNPREPARED','REPO_STALLED') NOT NULL"
    )


def downgrade() -> None:
    # Rows using the new member must go before the member does, or the
    # narrowing ALTER coerces them to an empty string.
    op.execute("DELETE FROM situations WHERE kind = 'REPO_STALLED'")
    op.execute(
        "ALTER TABLE situations MODIFY kind "
        "ENUM('SERVICE_JEOPARDY','MEETING_UNPREPARED') NOT NULL"
    )
