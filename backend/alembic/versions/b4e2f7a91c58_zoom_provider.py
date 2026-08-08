"""connection provider enum: add ZOOM

Zoom needs no new signal type and no new attention type - a Zoom meeting
normalizes to CALENDAR_EVENT and fires the existing meeting detector - so this
migration is one enum member and nothing else. That narrowness is the point.

Hand written for the usual reason: autogenerate diffs tables and columns, never
Enum members.

Revision ID: b4e2f7a91c58
Revises: a1c7e5b83d92
Create Date: 2026-08-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b4e2f7a91c58"
down_revision: Union[str, None] = "a1c7e5b83d92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = ("'GITHUB','GOOGLE_CALENDAR','GMAIL','GOOGLE_DRIVE','SLACK',"
        "'MICROSOFT_OUTLOOK_MAIL','MICROSOFT_OUTLOOK_CALENDAR','MICROSOFT_TEAMS',"
        "'MICROSOFT_ONEDRIVE','MICROSOFT_ONENOTE','MICROSOFT_TODO'")
_NEW = _OLD + ",'ZOOM'"


def upgrade() -> None:
    op.execute(f"ALTER TABLE connections MODIFY provider ENUM({_NEW}) NOT NULL")


def downgrade() -> None:
    # Signals reference connections, so they go first or the delete violates the
    # foreign key.
    op.execute("DELETE FROM signals WHERE connection_id IN (SELECT id FROM connections WHERE provider = 'ZOOM')")
    op.execute("DELETE FROM connections WHERE provider = 'ZOOM'")
    op.execute(f"ALTER TABLE connections MODIFY provider ENUM({_OLD}) NOT NULL")
