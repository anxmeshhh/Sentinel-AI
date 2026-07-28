"""provider enum: add SLACK

Phase 0 of the Slack provider. Widens the connections.provider enum so a Slack
workspace connection can be stored. Hand-written for the same reason as every
other enum change here: autogenerate diffs tables and columns, not Enum
*members*, so a new Provider exists only in Python until the DB enum is widened.

Revision ID: a1f4c8d90b21
Revises: 7c2a4f9e1b30
Create Date: 2026-07-28 20:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a1f4c8d90b21'
down_revision: Union[str, None] = '7c2a4f9e1b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE connections MODIFY provider "
        "ENUM('GITHUB','GOOGLE_CALENDAR','GMAIL','GOOGLE_DRIVE','SLACK') NOT NULL"
    )


def downgrade() -> None:
    # Rows using the new member must go before the member does, or the
    # narrowing ALTER coerces them to an empty string.
    op.execute("DELETE FROM connections WHERE provider = 'SLACK'")
    op.execute(
        "ALTER TABLE connections MODIFY provider "
        "ENUM('GITHUB','GOOGLE_CALENDAR','GMAIL','GOOGLE_DRIVE') NOT NULL"
    )
